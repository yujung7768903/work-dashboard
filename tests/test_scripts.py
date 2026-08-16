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
            self._run("stop.sh", "--port", str(self.port))

    def _skip_if_shared(self):
        # 인자 없는 재실행은 이 체크아웃의 서버를 전부 죽인다. 띄우기 전에 부른다
        if _serving_pids():
            self.skipTest("이 체크아웃에 다른 서버가 떠 있음")

    def test_start_then_stop(self):
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port), "start.sh 로 뜨지 않음")
        out = self._run("stop.sh", "--port", str(self.port))
        self.assertIn("종료", out)
        self.assertFalse(_listening(self.port), "stop.sh 로 멈추지 않음")

    def test_stop_without_server_is_quiet_success(self):
        self.assertIn(
            "돌고 있는 서버 없음", self._run("stop.sh", "--port", str(self.port))
        )

    def test_stop_with_port_leaves_other_servers_alone(self):
        other = _free_port()
        self._run("start.sh", "--port", str(other))
        self.addCleanup(self._run, "stop.sh", "--port", str(other))
        self.assertTrue(_wait_listening(other))
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        self._run("stop.sh", "--port", str(self.port))
        self.assertFalse(_listening(self.port), "지정한 포트가 안 멈췄다")
        self.assertTrue(_listening(other), "지정하지 않은 포트까지 멈췄다")

    def test_without_lan_only_this_machine(self):
        """기본은 루프백. 옵션을 안 준 실행이 LAN 에 열리면 인증 없는 화면이 그냥 노출된다"""
        lan = _lan_address()
        if not lan:
            self.skipTest("LAN 주소 없음")
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        self.assertFalse(_listening(self.port, lan), "옵션 없이 LAN 에 열렸다")

    def test_lan_opens_to_other_devices(self):
        """--lan 은 server.py 가 모르는 이름 — start.sh 가 --host 0.0.0.0 으로 바꿔 넘기고,
        찍는 주소도 0.0.0.0 이 아니라 붙여넣을 수 있는 실제 주소여야 한다"""
        lan = _lan_address()
        if not lan:
            self.skipTest("LAN 주소 없음")
        out = self._run("start.sh", "--lan", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        self.assertTrue(_listening(self.port, lan), "--lan 인데 LAN 주소로 안 열림")
        self.assertIn(f"http://{lan}:{self.port}", out)
        self.assertNotIn("0.0.0.0", out)

    def test_restart_keeps_lan_open_and_still_shows_the_address(self):
        """재실행은 --lan 이 아니라 --host 0.0.0.0 을 물려받는다 — 플래그 이름만 보면
        그때 주소도 경고도 사라진다"""
        lan = _lan_address()
        if not lan:
            self.skipTest("LAN 주소 없음")
        self._skip_if_shared()
        self._run("start.sh", "--lan", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        out = self._run("restart.sh")
        self.assertTrue(_wait_listening(self.port))
        self.assertTrue(_listening(self.port, lan), "재실행 뒤 LAN 이 닫혔다")
        self.assertIn(f"http://{lan}:{self.port}", out)

    def test_restart_inherits_port(self):
        """인자를 안 주면 죽는 서버의 포트를 물려받는다"""
        self._skip_if_shared()
        self._run("start.sh", "--port", str(self.port))
        self.assertTrue(_wait_listening(self.port))
        self.assertIn("종료", self._run("restart.sh"))
        self.assertTrue(_wait_listening(self.port), "restart.sh 가 같은 포트로 다시 띄우지 않음")


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _serving_pids():
    """이 체크아웃을 cwd 로 돌고 있는 서버 pid"""
    found = subprocess.run(
        ["bash", "-c", ". ./serving.sh; serving_pids"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return found.stdout.split()


def _lan_address():
    """이 기기의 LAN 주소. 못 찾으면 빈 문자열 (start.sh 와 같은 인터페이스 순서)"""
    for interface in ("en0", "en1"):
        try:
            found = subprocess.run(
                ["ipconfig", "getifaddr", interface], capture_output=True, text=True
            )
        except OSError:  # macOS 밖에는 ipconfig 가 없다
            return ""
        if found.returncode == 0 and found.stdout.strip():
            return found.stdout.strip()
    return ""


def _listening(port, host="127.0.0.1"):
    try:
        urllib.request.urlopen(f"http://{host}:{port}/api/usage", timeout=1).read()
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
