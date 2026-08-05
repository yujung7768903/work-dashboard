"""워크트리 서버 실행·재실행·중지. 보드 워크트리 탭의 케밥 메뉴가 부른다.

실행 방법은 워크트리 루트의 `run.sh` 하나로 본다 — 이 저장소의 관행이고(README "실행"),
백그라운드 실행·날짜별 로그·기동 대기까지 그 스크립트가 이미 한다. `run.sh` 가 없는
저장소는 실행하지 않고 그 사실을 그대로 알린다 — 진입점을 추측해서 띄우면 엉뚱한
프로세스가 포트를 문다.

중지는 release.kill_serving 을 그대로 쓴다 — 병합(worktrees.apply) 이 죽이는 것과
같은 판정이어야 화면에 보이는 포트와 어긋나지 않는다.
"""
import os
import socket
import subprocess
import time

from app.errors import Conflict, Validation
from app.services import release

RUN_SCRIPT = "run.sh"
# Stop 훅(hooks/worktree_serve.py) 이 고르는 범위와 같다 — 어느 쪽으로 띄웠든 한 대역에 모인다
PORT_RANGE = range(9080, 9140)
# run.sh 는 서버가 첫 줄(URL) 을 찍을 때까지 기다린 뒤 끝난다
START_TIMEOUT_SEC = 20
# SIGTERM 뒤 포트가 풀릴 때까지. 안 풀린 포트로 다시 띄우면 bind 가 그대로 실패한다
FREE_WAIT_SEC = 5
# run.sh 가 0 으로 끝나도 서버가 곧바로 죽는 경우가 있어 실제 응답까지 확인한다
READY_WAIT_SEC = 10
POLL_SEC = 0.2


def start(path, prefer=0):
    """그 워크트리에서 run.sh 로 서버를 띄운다. prefer 는 재실행이 물려주는 이전 포트"""
    running = release.serving_port(path)
    if running:
        raise Conflict(f"이미 :{running} 에 떠 있습니다. 다시 올리려면 '재실행' 을 쓰세요")
    script = os.path.join(path, RUN_SCRIPT)
    if not os.path.isfile(script):
        raise Validation(f"{RUN_SCRIPT} 이 없어 실행할 수 없습니다: {path}")
    port = prefer if prefer and _is_free(prefer) else free_port()
    if port is None:
        raise Conflict(
            f"비어 있는 포트가 없습니다 ({PORT_RANGE.start}~{PORT_RANGE.stop - 1})"
        )
    output = _run_script(script, path, port)
    if not _wait(lambda: _is_listening(port), READY_WAIT_SEC):
        raise Conflict(f":{port} 가 열리지 않았습니다. {output}")
    return {"port": port, "output": output}


def restart(path):
    """중지했다 같은 포트로 다시. 떠 있는 게 없으면 실행과 같다"""
    _ensure_not_self(path)
    previous = release.serving_port(path)
    stopped = stop(path)["stopped"]
    if previous:
        _wait(lambda: not _is_listening(previous), FREE_WAIT_SEC)
    return {**start(path, prefer=previous), "stopped": stopped}


def stop(path):
    """그 워크트리를 cwd 로 쓰는 서버에 SIGTERM. 떠 있는 게 없으면 빈 목록"""
    _ensure_not_self(path)
    return {
        "stopped": [
            {"pid": pid, "command": command}
            for pid, command in release.kill_serving(path)
        ]
    }


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
    """run.sh 를 그 워크트리에서. 서버는 스크립트가 nohup 으로 띄우므로 여기서
    기다려도 응답이 끝난 뒤에 남는다"""
    try:
        result = subprocess.run(
            [script, "--port", str(port)],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=START_TIMEOUT_SEC,
        )
    except Exception as error:
        raise Conflict(f"{RUN_SCRIPT} 실행 실패: {error}")
    if result.returncode:
        raise Conflict(
            f"{RUN_SCRIPT} 가 실패했습니다: {(result.stderr or result.stdout).strip()}"
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
