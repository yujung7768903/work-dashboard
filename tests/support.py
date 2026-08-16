"""테스트용 임시 DB·서버 픽스처."""
import os
import random
import socket
import subprocess
import sys
import tempfile

from app.constants import TEST_SERVER_PORTS
from app.db import connect

LISTENING_SERVER = (
    "import socket, time\n"
    "sock = socket.socket()\n"
    "sock.bind(('127.0.0.1', %d))\n"
    "sock.listen(1)\n"
    "print(sock.getsockname()[1], flush=True)\n"
    "time.sleep(30)\n"
)


def free_test_port():
    """테스트 전용 대역에서 비어 있는 포트 하나. 고르는 순서는 매번 다르다"""
    for port in random.sample(TEST_SERVER_PORTS, len(TEST_SERVER_PORTS)):
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"{TEST_SERVER_PORTS} 에 빈 포트가 없음")


def temp_db_path():
    """호출마다 새 임시 디렉토리 아래 DB 경로. sqlite3.Connection 에는 속성을 붙일 수 없어 경로를 따로 반환"""
    return os.path.join(tempfile.mkdtemp(), "test.db")


def temp_db(path=None):
    """임시 파일 DB 연결. 같은 경로를 다시 주면 재연결"""
    return connect(path or temp_db_path())


def serve(root, case, *flags, port=0):
    """그 디렉토리를 cwd 로 실제 포트를 듣는 프로세스. (프로세스, 포트) 를 돌려준다.
    port 를 주면 그 포트로, 0 이면 비어 있는 포트로 뜬다"""
    with open(os.path.join(root, "server.py"), "w") as handle:
        handle.write(LISTENING_SERVER % port)
    proc = subprocess.Popen(
        [sys.executable, *flags, "server.py"],
        cwd=root,
        stdout=subprocess.PIPE,
        text=True,
    )
    case.addCleanup(proc.stdout.close)
    case.addCleanup(_stop, proc)
    # 포트를 찍기 전에 이미 bind·listen 이 끝나 있으므로 이 줄만 읽으면 탐지 가능한 상태다
    return proc, int(proc.stdout.readline().strip())


def _stop(proc):
    """kill 만 하면 좀비가 남아 ResourceWarning 이 뜬다"""
    proc.kill()
    proc.wait(timeout=5)
