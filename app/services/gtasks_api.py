"""Google Tasks REST 호출과 인증 정보 보관. 도메인 판단은 하지 않고 HTTP 만 담당"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from app.constants import (
    GTASKS_API_ROOT,
    GTASKS_CONFIG_PATH,
    GTASKS_NO_SSL,
    GTASKS_PAGE_MAX,
    GTASKS_TIMEOUT_SEC,
    GTASKS_TOKEN_MARGIN_SEC,
    GTASKS_TOKEN_URL,
)
from app.errors import DomainError, NotFound, Validation

CONFIG_KEYS = ("client_id", "client_secret", "refresh_token")
UNAUTHORIZED = 401

try:  # ssl 없이 빌드된 Python 이 있다. 그러면 urllib 이 https 를 아예 못 연다
    import ssl  # noqa: F401

    HTTPS_READY = True
except ImportError:  # pragma: no cover - 정상 환경에서는 안 탄다
    HTTPS_READY = False


def require_https():
    """구글을 부르기 전에 막는다. 안 막으면 urllib 이 원인 모를 문구로 끝낸다"""
    if not HTTPS_READY:
        raise Validation(GTASKS_NO_SSL)


class GtasksError(DomainError):
    """구글 API 호출 실패. 본문에 사유가 담겨 온다"""


def load_config(path=None):
    resolved = path or GTASKS_CONFIG_PATH
    if not os.path.exists(resolved):
        raise Validation(f"구글 인증 정보 없음: {resolved} — 먼저 gtasks-auth 실행")
    with open(resolved, encoding="utf-8") as handle:
        config = json.load(handle)
    missing = [key for key in CONFIG_KEYS if not config.get(key)]
    if missing:
        raise Validation(f"인증 정보에 빠진 항목: {', '.join(missing)}")
    return config


def stored_client(path=None):
    """저장된 파일에서 client_id/secret 만 느슨하게 읽는다. 없거나 깨졌으면 빈 값

    load_config 는 refresh_token 까지 요구한다. 최초 인증은 그 토큰을 받으러 가는
    길이라 그때는 아직 없는 게 정상이므로 여기서는 있는 것만 꺼낸다
    """
    resolved = path or GTASKS_CONFIG_PATH
    if not os.path.exists(resolved):
        return {}
    try:
        with open(resolved, encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, ValueError):
        return {}
    return stored if isinstance(stored, dict) else {}


def save_config(config, path=None):
    """refresh_token 은 비밀번호와 같아 파일 권한을 본인만으로 좁힌다"""
    resolved = path or GTASKS_CONFIG_PATH
    parent = os.path.dirname(resolved)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(resolved, "w", encoding="utf-8") as handle:
        json.dump(config, handle, ensure_ascii=False, indent=2)
    os.chmod(resolved, 0o600)
    return resolved


def post_form(url, fields):
    """토큰 발급·갱신용 form POST. 인증 흐름과 클라이언트가 같이 쓴다

    모든 구글 호출이 access token 을 받으러 여기를 지난다 — 마지막 관문으로 한 번 더 본다
    """
    require_https()
    body = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=body, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=GTASKS_TIMEOUT_SEC) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise GtasksError(f"구글 토큰 요청 실패 ({error.code}): {_body(error)}")
    except urllib.error.URLError as error:
        raise GtasksError(f"구글에 연결할 수 없음: {error.reason}")


class Client:
    """access_token 은 인스턴스 수명 동안만 들고 있음 (동기화 1회면 충분)"""

    def __init__(self, config=None):
        self._config = config or load_config()
        self._token = None
        self._expires_at = 0

    def lists(self):
        return self._paged("GET", "/users/@me/lists")

    def create_list(self, title):
        return self._call("POST", "/users/@me/lists", body={"title": title})

    def tasks(self, list_id):
        """완료·숨김 포함. 숨김을 빼면 폰에서 체크한 할일이 응답에서 사라진다"""
        params = {"showCompleted": "true", "showHidden": "true"}
        return self._paged("GET", f"/lists/{list_id}/tasks", params)

    def insert(self, list_id, body, parent=None):
        """parent 는 본문이 아니라 쿼리 파라미터다 — 본문에 넣으면 조용히 무시되고
        하위 태스크가 최상위로 올라간다 (구글은 1단계 중첩만 허용)"""
        params = {"parent": parent} if parent else None
        return self._call("POST", f"/lists/{list_id}/tasks", params=params, body=body)

    def patch(self, list_id, task_id, body):
        return self._call("PATCH", f"/lists/{list_id}/tasks/{task_id}", body=body)

    def delete(self, list_id, task_id):
        self._call("DELETE", f"/lists/{list_id}/tasks/{task_id}")

    def _paged(self, method, path, params=None):
        """nextPageToken 을 끝까지 따라감. 기본 페이지가 20건이라 안 따라가면 조용히 잘린다"""
        items = []
        page = dict(params or {}, maxResults=GTASKS_PAGE_MAX)
        while True:
            payload = self._call(method, path, params=page) or {}
            items.extend(payload.get("items") or [])
            token = payload.get("nextPageToken")
            if not token:
                return items
            page = dict(page, pageToken=token)

    def _call(self, method, path, params=None, body=None, retried=False):
        url = GTASKS_API_ROOT + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(url, method=method)
        request.add_header("Authorization", f"Bearer {self._access_token()}")
        if body is not None:
            request.data = json.dumps(body).encode("utf-8")
            request.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(request, timeout=GTASKS_TIMEOUT_SEC) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else None
        except urllib.error.HTTPError as error:
            return self._on_http_error(error, method, path, params, body, retried)
        except urllib.error.URLError as error:
            raise GtasksError(f"구글에 연결할 수 없음: {error.reason}")

    def _on_http_error(self, error, method, path, params, body, retried):
        """401 은 토큰 만료로 보고 한 번만 다시 받아 재시도. 404 는 도메인 쪽에서 처리"""
        if error.code == UNAUTHORIZED and not retried:
            self._token = None
            return self._call(method, path, params, body, retried=True)
        if error.code == 404:
            raise NotFound(f"구글에 없는 대상: {path}")
        raise GtasksError(f"구글 API 실패 ({error.code}) {path}: {_body(error)}")

    def _access_token(self):
        if self._token and time.time() < self._expires_at:
            return self._token
        payload = post_form(
            GTASKS_TOKEN_URL,
            {
                "client_id": self._config["client_id"],
                "client_secret": self._config["client_secret"],
                "refresh_token": self._config["refresh_token"],
                "grant_type": "refresh_token",
            },
        )
        self._token = payload["access_token"]
        expires_in = payload.get("expires_in", 3600) - GTASKS_TOKEN_MARGIN_SEC
        self._expires_at = time.time() + expires_in
        return self._token


def _body(error):
    try:
        return error.read().decode("utf-8")[:300]
    except Exception:
        return "(본문 없음)"
