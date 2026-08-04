"""start.sh·stop.sh·restart.sh 검사.

run.sh 를 start.sh 로 바꿨을 때 restart.sh 의 `exec ./run.sh` 가 남아
"서버를 죽이고 다시 못 띄우는" 상태가 됐다 — 그 자국을 잡는 테스트가 첫 번째다.
"""
import os
import re
import socket
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.request

from tests.support import temp_db_path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = ("start.sh", "stop.sh", "restart.sh", "serving.sh")
REFERENCE = re.compile(r"(?:\./|\. \./)([a-z_]+\.sh)")
BOOT_TIMEOUT_SEC = 10


class ScriptReferenceTest(unittest.TestCase):
    def test_scripts_exist_and_are_executable(self):
        for name in SCRIPTS:
            path = os.path.join(ROOT, name)
            self.assertTrue(os.path.isfile(path), f"{name} 없음")
            # serving.sh 는 source 전용이라 실행 권한을 요구하지 않는다
            if name != "serving.sh":
                self.assertTrue(os.access(path, os.X_OK), f"{name} 실행 권한 없음")

    def test_referenced_scripts_exist(self):
        """스크립트가 부르는 다른 스크립트가 실제로 있어야 한다 — 이름을 바꿀 때 깨지는 자리"""
        for name in SCRIPTS:
            with open(os.path.join(ROOT, name)) as handle:
                body = handle.read()
            for referenced in set(REFERENCE.findall(body)):
                self.assertTrue(
                    os.path.isfile(os.path.join(ROOT, referenced)),
                    f"{name} 이 없는 {referenced} 를 부른다",
                )

    def test_bash_syntax(self):
        for name in SCRIPTS:
            result = subprocess.run(
                ["bash", "-n", os.path.join(ROOT, name)], capture_output=True, text=True
            )
            self.assertEqual(0, result.returncode, f"{name}: {result.stderr}")


class StartStopTest(unittest.TestCase):
    """실제로 띄우고 멈춘다. DB 는 임시 파일로 돌려 사용자 DB 를 건드리지 않는다"""

    def setUp(self):
        self.port = _free_port()
        self.env = dict(os.environ, WORK_DASHBOARD_DB=temp_db_path())
        self.addCleanup(self._stop)

    def _run(self, script, *argv):
        result = subprocess.run(
            [os.path.join(ROOT, script), *argv],
            cwd=ROOT,
            capture_output=True,
            text=True,
            env=self.env,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout

    def _stop(self):
        if _listening(self.port):
            self._run("stop.sh")

    def test_start_then_stop(self):
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port), "start.sh 로 뜨지 않음")
        out = self._run("stop.sh")
        self.assertIn("종료", out)
        self.assertFalse(_listening(self.port), "stop.sh 로 멈추지 않음")

    def test_stop_without_server_is_quiet_success(self):
        self.assertIn("돌고 있는 서버 없음", self._run("stop.sh"))

    def test_restart_inherits_port(self):
        """인자를 안 주면 죽는 서버의 포트를 물려받는다"""
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        self.assertIn("종료", self._run("restart.sh"))
        self.assertTrue(_wait_listening(self.port), "restart.sh 가 같은 포트로 다시 띄우지 않음")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _listening(port):
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/usage", timeout=1).read()
        return True
    except (urllib.error.URLError, OSError):
        return False


def _wait_listening(port, timeout=BOOT_TIMEOUT_SEC):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _listening(port):
            return True
        time.sleep(0.2)
    return False


if __name__ == "__main__":
    sys.exit(unittest.main())
