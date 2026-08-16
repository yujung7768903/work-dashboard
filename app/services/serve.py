"""워크트리 서버 실행·재실행·중지. 보드 워크트리 탭의 케밥 메뉴가 부른다.

실행 방법은 워크트리 루트의 `start.sh`(옛 이름 `run.sh`) 로 본다 — 이 저장소의
관행이고(README "Quickstart"), 백그라운드 실행·날짜별 로그·기동 대기까지 그 스크립트가 이미
한다. 둘 다 없는 저장소는 실행하지 않고 그 사실을 그대로 알린다 — 진입점을 추측해서
띄우면 엉뚱한 프로세스가 포트를 문다.

중지는 release.kill_serving 을 그대로 쓴다 — 병합(worktrees.apply) 이 죽이는 것과
같은 판정이어야 화면에 보이는 포트와 어긋나지 않는다.

셋 다 사람이 읽을 문장(message)을 함께 돌려준다 — 실행은 몇 초 걸리고 끝나도 화면에는
포트 배지가 조용히 붙을 뿐이라, 수행 중인지 끝난 건지 구분이 안 된다. 화면은 그 문장을
그대로 띄운다(병합이 세션을 끊었을 때의 알림과 같은 경로).
"""
import os
import socket
import subprocess
import time

from app.constants import DEFAULT_HOST, DEFAULT_PORT
from app.errors import Conflict, Validation
from app.services import release

# 두 이름을 다 본다 — 이 저장소는 start.sh 로 바꿨지만, 바꾸기 전 브랜치로 만든
# 워크트리에는 아직 run.sh 가 있다. 앞의 것부터 찾는다 (없는 이름을 지어내지는 않는다)
RUN_SCRIPTS = ("start.sh", "run.sh")
# Stop 훅(hooks/worktree_serve.py) 이 고르는 범위와 같다 — 어느 쪽으로 띄웠든 한 대역에 모인다.
# 9080(DEFAULT_PORT) 은 빠져 있다 — 메인 체크아웃(master) 자리다. 워크트리가 물면
# master 를 늘 같은 주소로 열 수 없어 북마크가 그때그때 다른 브랜치를 가리킨다.
# 실제로 못 물게 막는 것은 server.py 쪽이고 여기는 애초에 고르지 않는 쪽
PORT_RANGE = range(DEFAULT_PORT + 1, 9140)
# 실행 스크립트는 서버가 첫 줄(URL) 을 찍을 때까지 기다린 뒤 끝난다
START_TIMEOUT_SEC = 20
# SIGTERM 뒤 포트가 풀릴 때까지. 안 풀린 포트로 다시 띄우면 bind 가 그대로 실패한다
FREE_WAIT_SEC = 5
# 스크립트가 0 으로 끝나도 서버가 곧바로 죽는 경우가 있어 실제 응답까지 확인한다
READY_WAIT_SEC = 10
POLL_SEC = 0.2


def run_script(path):
    """그 워크트리의 실행 스크립트 경로. 없으면 빈 문자열"""
    found = (os.path.join(path, name) for name in RUN_SCRIPTS)
    return next((script for script in found if os.path.isfile(script)), "")


def start(path, prefer=0):
    """그 워크트리의 실행 스크립트로 서버를 띄운다. prefer 는 재실행이 물려주는 이전 포트"""
    running = release.serving_port(path)
    if running:
        raise Conflict(f"이미 :{running} 에 떠 있습니다. 다시 올리려면 '재실행' 을 쓰세요")
    script = run_script(path)
    if not script:
        raise Validation(
            f"{'·'.join(RUN_SCRIPTS)} 중 아무것도 없어 실행할 수 없습니다: {path}"
        )
    # prefer 가 9080 이면 물려받지 않는다 — 예전에 그 포트로 뜬 워크트리가 재실행으로
    # 계속 master 자리를 차지하는 것을 막는다
    keep = prefer and prefer != DEFAULT_PORT and _is_free(prefer)
    port = prefer if keep else free_port()
    if port is None:
        raise Conflict(
            f"비어 있는 포트가 없습니다 ({PORT_RANGE.start}~{PORT_RANGE.stop - 1})"
        )
    output = _run_script(script, path, port)
    if not _wait(lambda: _is_listening(port), READY_WAIT_SEC):
        raise Conflict(f":{port} 가 열리지 않았습니다. {output}")
    return {"port": port, "output": output, "message": _url_message("실행했습니다", port)}


def restart(path):
    """중지했다 같은 포트로 다시. 떠 있는 게 없으면 실행과 같다"""
    _ensure_not_self(path)
    previous = release.serving_port(path)
    stopped = stop(path)["stopped"]
    if previous:
        _wait(lambda: not _is_listening(previous), FREE_WAIT_SEC)
    started = start(path, prefer=previous)
    return {
        **started,
        "stopped": stopped,
        "message": _url_message("재실행했습니다", started["port"]),
    }


def stop(path):
    """그 워크트리를 cwd 로 쓰는 서버에 SIGTERM. 떠 있는 게 없으면 빈 목록"""
    _ensure_not_self(path)
    stopped = [
        {"pid": pid, "command": command} for pid, command in release.kill_serving(path)
    ]
    # 아무것도 안 죽였을 때 "종료했습니다" 로 끝나면 뭘 했는지 오해한다
    return {
        "stopped": stopped,
        "message": "종료했습니다" if stopped else "종료할 서버가 없었습니다",
    }


def _url_message(done, port):
    """실행·재실행 안내. 주소를 함께 준다 — 포트만으로는 바로 열어볼 수 없다"""
    return f"{done} — http://{DEFAULT_HOST}:{port}/"


def _ensure_not_self(path):
    """지금 이 요청을 처리하는 서버가 그 워크트리의 서버면 손대지 않는다.

    자기를 죽이면 응답을 돌려줄 주체가 없고, release.kill_serving 은 자기 pid 를 건너뛰어
    조용히 아무것도 죽이지 않는다 — 그 상태로 다시 실행하면 "이미 떠 있다" 로 끝난다.
    그 워크트리의 대시보드를 보면서 자기 자신을 재실행하려 할 때 걸린다
    """
    if os.path.realpath(path) == os.path.realpath(os.getcwd()):
        raise Validation(
            "이 화면을 띄운 서버입니다. 다른 포트의 대시보드에서 하거나"
            " 그 워크트리에서 ./restart.sh 를 쓰세요"
        )


def free_port():
    """비어 있는 첫 포트. 다 차 있으면 None"""
    return next((port for port in PORT_RANGE if _is_free(port)), None)


def _run_script(script, path, port):
    """실행 스크립트를 그 워크트리에서. 서버는 스크립트가 nohup 으로 띄우므로 여기서
    기다려도 응답이 끝난 뒤에 남는다"""
    name = os.path.basename(script)
    try:
        result = subprocess.run(
            [script, "--port", str(port)],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_SEC,
        )
    except Exception as error:
        raise Conflict(f"{name} 실행 실패: {error}")
    if result.returncode:
        raise Conflict(
            f"{name} 가 실패했습니다: {(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip()


def _is_free(port):
    """bind 로 판정. 고를 때만 쓴다 — 남이 쓰고 있는지만 보면 되기 때문"""
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _is_listening(port):
    """실제로 받아주는지. 기동·종료 확인은 bind 가 아니라 이쪽으로 본다 —
    bind 가 막히는 이유는 다른 프로세스일 수도 있어 내 서버가 떴다는 근거가 못 된다"""
    with socket.socket() as probe:
        probe.settimeout(POLL_SEC)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _wait(ready, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if ready():
            return True
        time.sleep(POLL_SEC)
    return False
