"""④ 자율 실행의 tick 을 부르는 스케줄러 등록·점검. 판정은 autorun 이 하고 여기는 트리거만 본다.

crontab 이 아니라 launchd 를 쓴다 — cron 은 사용자 로그인 세션 밖이라 키체인을 못 읽고,
tick 이 띄우는 `claude --bg` 가 'Not logged in' 으로 실패한다. 같은 이유로 이 맥의 리밋
재개(`~/.claude/scripts/claude-limit-watch.py`)도 LaunchAgent 로만 돈다 — 그 파일 주석에
실측으로 적혀 있다("반드시 LaunchAgent(gui/$UID) 로 띄울 것"). crontab 에 걸면 등록은
되지만 잡이 인증에서 죽으므로, 켜 놓고도 아무것도 안 되는 상태가 그대로 재현된다.

등록 여부를 상태 조회에 붙이는 이유 — `autorun on` 은 '돌아도 된다' 는 플래그일 뿐이고
tick 을 5분마다 부르는 주체는 따로 있어야 한다. 그 둘이 갈라져 있으면 켜 놓고도 아무
일이 일어나지 않는데 화면에는 on 만 보인다. 실제로 그렇게 오래 멈춰 있었고, 아무도
그 사실을 알 수 없었다
"""
import os
import plistlib
import subprocess

from app.constants import (
    AUTORUN_AGENT_LABEL,
    AUTORUN_AGENT_LOG,
    AUTORUN_AGENT_PLIST,
    AUTORUN_AGENT_PYTHON,
    AUTORUN_TICK_INTERVAL_SEC,
    LAUNCHCTL_TIMEOUT_SEC,
)
from app.services import release


def status():
    """등록 상태. plist 가 있어도 로드되지 않았으면 안 도는 것이라 둘을 따로 본다"""
    return {
        "plist": AUTORUN_AGENT_PLIST,
        "written": os.path.exists(AUTORUN_AGENT_PLIST),
        "loaded": _loaded(),
        "interval_sec": AUTORUN_TICK_INTERVAL_SEC,
    }


def installed():
    state = status()
    return state["written"] and state["loaded"]


def install(repo_root=None):
    """plist 를 쓰고 다시 읽힌다. 이미 있어도 덮어쓴다 — 저장소를 옮겼으면 경로가 바뀐다"""
    root = release.main_checkout(repo_root or _repo_root())
    for path in (AUTORUN_AGENT_PLIST, AUTORUN_AGENT_LOG):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(AUTORUN_AGENT_PLIST, "wb") as handle:
        plistlib.dump(_plist(root), handle)
    # 이전 등록이 남아 있으면 새 plist 를 읽지 않는다. 처음 등록이면 실패하는데 무시한다
    _launchctl("unload", AUTORUN_AGENT_PLIST)
    loaded = _launchctl("load", AUTORUN_AGENT_PLIST)
    return dict(status(), repo_root=root, error=_error(loaded))


def _plist(root):
    """RunAtLoad 를 켜 두면 등록 직후 한 번 돈다 — 5분을 기다리지 않고 바로 확인된다"""
    return {
        "Label": AUTORUN_AGENT_LABEL,
        "ProgramArguments": [
            AUTORUN_AGENT_PYTHON,
            os.path.join(root, "dash.py"),
            "autorun-tick",
        ],
        "StartInterval": AUTORUN_TICK_INTERVAL_SEC,
        "RunAtLoad": True,
        "WorkingDirectory": root,
        "StandardOutPath": AUTORUN_AGENT_LOG,
        "StandardErrorPath": AUTORUN_AGENT_LOG,
        "ProcessType": "Background",
    }


def _repo_root():
    """이 파일이 든 저장소. `app/services/scheduler.py` 에서 세 단계 위가 루트다.

    워크트리에서 등록해도 main_checkout 이 본 저장소로 되돌린다 — 워크트리는 작업이
    끝나면 지워지므로 그 경로가 plist 에 박히면 다음 tick 부터 파일을 못 찾는다
    """
    return os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )


def _loaded():
    result = _launchctl("list", AUTORUN_AGENT_LABEL)
    return bool(result) and result.returncode == 0


def _launchctl(*args):
    """실패해도 예외를 올리지 않는다 — 등록은 부가 기능이고 판정 자체는 tick 이 한다"""
    try:
        return subprocess.run(
            ["launchctl", *args],
            capture_output=True,
            text=True,
            timeout=LAUNCHCTL_TIMEOUT_SEC,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _error(result):
    if result is None:
        return "launchctl 을 실행할 수 없음"
    if result.returncode == 0:
        return ""
    detail = (result.stderr or result.stdout or "").strip()
    return detail or f"launchctl 실패 (종료 코드 {result.returncode})"
