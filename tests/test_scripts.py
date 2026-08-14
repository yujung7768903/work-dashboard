"""start.sh·stop.sh·restart.sh 검사.

run.sh 를 start.sh 로 바꿨을 때 restart.sh 의 `exec ./run.sh` 가 남아
"서버를 죽이고 다시 못 띄우는" 상태가 됐다 — 그 자국을 잡는 테스트가 첫 번째다.
"""
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
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
    """실제로 띄우고 멈춘다. DB 는 임시 파일로 돌려 사용자 DB 를 건드리지 않는다.

    저장소 자리가 아니라 임시 디렉토리에 스크립트를 복사해 놓고 거기서 돌린다.
    stop.sh 는 '이 디렉토리를 cwd 로 도는 서버' 를 전부 멈추므로, 저장소에서 그대로
    돌리면 사람이 그 워크트리에 띄워 둔 대시보드까지 같이 죽는다 — 실제로 죽였다
    """

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.mkdtemp(prefix="wd-scripts-")
        for name in SCRIPTS:
            shutil.copy2(os.path.join(ROOT, name), os.path.join(cls.dir, name))
        # 서버가 돌려면 있어야 하는 것들. 복사 대신 링크라 원본을 그대로 검사한다
        # (server.py 는 자기 위치 기준으로 static 을 찾으므로 그것도 걸어 준다)
        for name in ("server.py", "app", "static"):
            os.symlink(os.path.join(ROOT, name), os.path.join(cls.dir, name))
        cls.addClassCleanup(shutil.rmtree, cls.dir, True)

    def setUp(self):
        self.port = _free_port()
        self.env = dict(os.environ, WORK_DASHBOARD_DB=temp_db_path())
        self.addCleanup(self._stop)

    def _run(self, script, *argv):
        result = subprocess.run(
            [os.path.join(self.dir, script), *argv],
            cwd=self.dir,
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
