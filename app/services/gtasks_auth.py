"""구글 최초 인증 1회. refresh_token 만 받아내면 이후로는 쓰이지 않는다

구글이 out-of-band(코드 복붙) 방식을 막아서 로컬 콜백 서버가 유일한 길이다.
데스크톱 OAuth 클라이언트는 127.0.0.1 이면 포트를 미리 등록하지 않아도 받아준다
"""
import base64
import hashlib
import os
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.constants import (
    GTASKS_AUTH_HOST,
    GTASKS_CLIENT_ID_ENV,
    GTASKS_CLIENT_SECRET_ENV,
    GTASKS_AUTH_TIMEOUT_SEC,
    GTASKS_AUTH_URL,
    GTASKS_SCOPE,
    GTASKS_TOKEN_URL,
)
from app.errors import Validation
from app.services import gtasks_api

DONE_PAGE = "<html><body><h3>인증 완료. 터미널로 돌아가세요.</h3></body></html>"
VERIFIER_BYTES = 64


def authorize(client_id=None, client_secret=None, open_browser=True):
    """브라우저 동의 → 코드 → refresh_token. 받은 인증 정보를 저장하고 경로를 반환

    자격증명은 인자 > 환경변수 > 저장된 gtasks.json 순으로 찾는다. client_id/secret 을
    파일에 미리 적어두면 이 명령은 인자 없이 돌아간다.

    이 함수는 최초 1회만 쓰인다. refresh_token 은 구글 동의 화면을 거쳐야만 나오므로
    손으로 적어 넣을 수 없고, 한 번 받고 나면 이후 동기화는 그것만으로 돈다
    """
    stored = gtasks_api.stored_client()
    client_id = client_id or os.environ.get(GTASKS_CLIENT_ID_ENV) or stored.get("client_id")
    client_secret = (
        client_secret
        or os.environ.get(GTASKS_CLIENT_SECRET_ENV)
        or stored.get("client_secret")
    )
    if not client_id or not client_secret:
        raise Validation(
            "client_id 와 client_secret 이 모두 필요함 —"
            f" --client-id/--client-secret, {GTASKS_CLIENT_ID_ENV}/"
            f"{GTASKS_CLIENT_SECRET_ENV} 환경변수,"
            f" 또는 {gtasks_api.GTASKS_CONFIG_PATH} 에 두 키를 적어 둔다"
        )
    # 동의가 실패하거나 시간이 지나도 받아 둔 값은 남긴다 — 다시 타이핑하게 하지 않는다.
    # 기존 내용을 펼쳐 담아야 이미 있던 refresh_token 이 날아가지 않는다
    if (stored.get("client_id"), stored.get("client_secret")) != (client_id, client_secret):
        gtasks_api.save_config(
            {**stored, "client_id": client_id, "client_secret": client_secret}
        )
    verifier, challenge = _pkce_pair()
    # with 로 감싸야 브라우저를 띄우기 전에 실패해도 포트가 물린 채 남지 않는다
    with HTTPServer((GTASKS_AUTH_HOST, 0), _CallbackHandler) as server:
        server.timeout = GTASKS_AUTH_TIMEOUT_SEC
        server.auth_code = None
        server.auth_error = None
        redirect_uri = f"http://{GTASKS_AUTH_HOST}:{server.server_port}"
        url = _consent_url(client_id, redirect_uri, challenge)
        print(f"브라우저에서 아래 주소를 열어 승인하세요:\n{url}")
        if open_browser:
            webbrowser.open(url)
        server.handle_request()
        auth_code, auth_error = server.auth_code, server.auth_error
    if auth_error:
        raise Validation(f"구글이 인증을 거부함: {auth_error}")
    if not auth_code:
        raise Validation(f"{GTASKS_AUTH_TIMEOUT_SEC}초 안에 승인이 오지 않음")
    token = gtasks_api.post_form(
        GTASKS_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": auth_code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    if not token.get("refresh_token"):
        raise Validation(
            "refresh_token 이 오지 않음 — 이미 승인된 앱이면"
            " myaccount.google.com/permissions 에서 지우고 다시 실행"
        )
    return gtasks_api.save_config(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": token["refresh_token"],
        }
    )


def _consent_url(client_id, redirect_uri, challenge):
    """offline + consent 라야 refresh_token 이 온다. 둘 중 하나만 빠져도 조용히 생략됨"""
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": GTASKS_SCOPE,
            "access_type": "offline",
            "prompt": "consent",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{GTASKS_AUTH_URL}?{query}"


def _pkce_pair():
    """데스크톱 클라이언트에 구글이 권장하는 코드 교환 보호"""
    verifier = _b64(os.urandom(VERIFIER_BYTES))
    challenge = _b64(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        self.server.auth_code = (query.get("code") or [None])[0]
        self.server.auth_error = (query.get("error") or [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DONE_PAGE.encode("utf-8"))

    def log_message(self, *args):
        """콘솔에 접근 로그를 찍지 않는다 — 안내 문구를 밀어낸다"""
