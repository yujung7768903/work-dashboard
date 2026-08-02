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
    GTASKS_AUTH_TIMEOUT_SEC,
    GTASKS_AUTH_URL,
    GTASKS_SCOPE,
    GTASKS_TOKEN_URL,
)
from app.errors import Validation
from app.services import gtasks_api

DONE_PAGE = "<html><body><h3>인증 완료. 터미널로 돌아가세요.</h3></body></html>"
VERIFIER_BYTES = 64


def authorize(client_id, client_secret, open_browser=True):
    """브라우저 동의 → 코드 → refresh_token. 받은 인증 정보를 저장하고 경로를 반환"""
    if not client_id or not client_secret:
        raise Validation("client_id 와 client_secret 이 모두 필요함")
    verifier, challenge = _pkce_pair()
    server = HTTPServer((GTASKS_AUTH_HOST, 0), _CallbackHandler)
    server.timeout = GTASKS_AUTH_TIMEOUT_SEC
    server.auth_code = None
    server.auth_error = None
    redirect_uri = f"http://{GTASKS_AUTH_HOST}:{server.server_port}"
    url = _consent_url(client_id, redirect_uri, challenge)
    print(f"브라우저에서 아래 주소를 열어 승인하세요:\n{url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.handle_request()
    finally:
        server.server_close()
    if server.auth_error:
        raise Validation(f"구글이 인증을 거부함: {server.auth_error}")
    if not server.auth_code:
        raise Validation(f"{GTASKS_AUTH_TIMEOUT_SEC}초 안에 승인이 오지 않음")
    token = gtasks_api.post_form(
        GTASKS_TOKEN_URL,
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": server.auth_code,
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
