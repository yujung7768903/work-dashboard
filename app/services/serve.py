"""워크트리 서버 실행·재실행·중지. 보드 워크트리 탭의 케밥 메뉴가 부른다.

셋 다 워크트리 루트의 스크립트를 그대로 부른다 — `start.sh`(옛 이름 `run.sh`) ·
`stop.sh` · `restart.sh`. 백그라운드 실행·날짜별 로그·중복 방지·인자 물려받기를 그쪽이
이미 하고, 무엇보다 '이 디렉토리의 서버' 판정이 한 곳에만 있어야 한다. 여기서 따로
죽이거나 조립하면 판정이 갈려 한쪽이 남의 서버를 죽인다. 실행 스크립트가 아예 없는
저장소는 실행하지 않고 그 사실을 알린다 — 진입점을 추측해서 띄우면 엉뚱한 프로세스가
포트를 문다. stop.sh·restart.sh 가 없던 시절의 워크트리에서만 예전 파이썬 경로로 떨어진다.

이 모듈에 남는 것은 셸이 모르는 것뿐이다 — 어느 포트를 줄지(free_port, 9080 은 메인
체크아웃 자리라 뺀다), 자기 자신을 죽이지 않기(_ensure_not_self), 화면에 돌려줄 문장.

셋 다 사람이 읽을 문장(message)을 함께 돌려준다 — 실행은 몇 초 걸리고 끝나도 화면에는
포트 배지가 조용히 붙을 뿐이라, 수행 중인지 끝난 건지 구분이 안 된다. 화면은 그 문장을
그대로 띄운다(병합이 세션을 끊었을 때의 알림과 같은 경로).
"""
import os
import re
import socket
import subprocess
import time

from app.constants import DEFAULT_HOST, DEFAULT_PORT
from app.errors import Conflict, Validation
from app.services import release

# 두 이름을 다 본다 — 이 저장소는 start.sh 로 바꿨지만, 바꾸기 전 브랜치로 만든
# 워크트리에는 아직 run.sh 가 있다. 앞의 것부터 찾는다 (없는 이름을 지어내지는 않는다)
RUN_SCRIPTS = ("start.sh", "run.sh")
# 멈추기·다시 띄우기도 같은 스크립트를 쓴다. 셸에 없던 시절의 워크트리는 없을 수 있어
# 있으면 쓰고 없으면 예전 파이썬 경로로 떨어진다
STOP_SCRIPTS = ("stop.sh",)
RESTART_SCRIPTS = ("restart.sh",)
# start.sh·restart.sh 가 마지막에 찍는 줄에서 포트를 읽는다 (`http://127.0.0.1:9081`)
PORT_LINE = re.compile(r"https?://[^\s:]+:(\d+)")
# stop.sh 가 죽인 pid 를 찍는 줄 (`종료 12345`)
STOPPED_LINE = re.compile(r"^종료 (\d+)", re.MULTILINE)
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
    return _script(path, RUN_SCRIPTS)


def _script(path, names):
    """앞의 이름부터 찾는다. 없는 이름을 지어내지는 않는다"""
    found = (os.path.join(path, name) for name in names)
    return next((script for script in found if os.path.isfile(script)), "")


def _port_of(output):
    """스크립트가 찍은 주소에서 포트. 못 찾으면 None"""
    found = PORT_LINE.search(output or "")
    return int(found.group(1)) if found else None


def _stopped_pids(output):
    """stop.sh 가 죽였다고 찍은 pid 목록. 화면이 몇 개 멈췄는지 보여준다"""
    return [{"pid": int(pid), "command": ""} for pid in STOPPED_LINE.findall(output or "")]


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
    output = _run_script(script, path, "--port", str(port))
    if not _wait(lambda: _is_listening(port), READY_WAIT_SEC):
        raise Conflict(f":{port} 가 열리지 않았습니다. {output}")
    return {"port": port, "output": output, "message": _url_message("실행했습니다", port)}


def restart(path):
    """그 워크트리의 restart.sh 로. 포트·--lan 같은 인자는 스크립트가 물려받는다.

    떠 있는 게 없으면 restart.sh 를 부르지 않는다 — 인자 없는 그것은 기본 포트(9080)로
    띄우고, 그 자리는 메인 체크아웃 것이다. 그 경우는 실행과 같게 빈 포트를 골라 준다
    """
    _ensure_not_self(path)
    previous = release.serving_port(path)
    if not previous:
        return start(path)
    script = _script(path, RESTART_SCRIPTS)
    if not script:
        # restart.sh 가 없던 시절의 워크트리. 예전처럼 파이썬에서 조립한다
        stopped = stop(path)["stopped"]
        _wait(lambda: not _is_listening(previous), FREE_WAIT_SEC)
        started = start(path, prefer=previous)
        return {**started, "stopped": stopped,
                "message": _url_message("재실행했습니다", started["port"])}
    output = _run_script(script, path)
    port = _port_of(output) or previous
    if not _wait(lambda: _is_listening(port), READY_WAIT_SEC):
        raise Conflict(f":{port} 가 열리지 않았습니다. {output}")
    return {
        "port": port,
        "output": output,
        "stopped": _stopped_pids(output),
        "message": _url_message("재실행했습니다", port),
    }


def stop(path):
    """그 워크트리의 stop.sh 로 멈춘다. 떠 있는 게 없으면 빈 목록.

    파이썬에서 직접 죽이지 않는 이유 — '이 디렉토리의 서버' 판정이 셸과 갈리면
    한쪽이 남의 서버를 죽인다. 스크립트가 없는 옛 워크트리에서만 예전 경로로 떨어진다
    """
    _ensure_not_self(path)
    script = _script(path, STOP_SCRIPTS)
    if script:
        stopped = _stopped_pids(_run_script(script, path))
    else:
        stopped = [
            {"pid": pid, "command": command}
            for pid, command in release.kill_serving(path)
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


def _run_script(script, path, *args):
    """스크립트를 그 워크트리에서. 서버는 스크립트가 nohup 으로 띄우므로 여기서
    기다려도 응답이 끝난 뒤에 남는다"""
    name = os.path.basename(script)
    try:
        result = subprocess.run(
            [script, *args],
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
