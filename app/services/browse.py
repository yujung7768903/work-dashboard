"""로컬 파일시스템 폴더 탐색과 탐색기 띄우기. 할일 케밥의 "시작" 이 작업 위치를
못 정했을 때 화면이 사람에게 물어 받는 경로 선택기, 그리고 note 안의 경로를 눌러
탐색기로 여는 것이 여기를 부른다.

서버가 도는 컴퓨터의 파일시스템을 그대로 읽을 뿐이다 — 이 대시보드는 1인용·인증 없이
로컬에서만 돈다는 전제(README)라, 파일 하나 더 읽는다고 새 위험이 생기지 않는다.
"""
import os
import platform
import subprocess
import sys

from app.errors import Validation

DEFAULT_ROOT = os.path.expanduser("~")
DARWIN = "darwin"
WSL = "wsl"
LINUX = "linux"
REVEAL_TIMEOUT_SEC = 10


def list_dir(path=None):
    """path 이하의 하위 폴더 목록 + 각 폴더가 git 저장소인지.

    파일은 안 보여준다 — 고를 대상은 항상 디렉토리다. 숨김 폴더(.로 시작)는
    노이즈만 늘어 뺀다. 못 읽는 폴더(권한 없음)는 빈 목록으로 넘긴다 — 그 폴더
    하나 때문에 탐색 전체가 죽으면 안 된다.
    """
    target = os.path.realpath(os.path.expanduser(path) if path else DEFAULT_ROOT)
    if not os.path.isdir(target):
        raise Validation(f"디렉토리가 아님: {target}")
    try:
        names = os.listdir(target)
    except OSError:
        names = []
    entries = [
        {
            "name": name,
            "path": os.path.join(target, name),
            "is_git_repo": os.path.exists(os.path.join(target, name, ".git")),
        }
        for name in sorted(names, key=str.lower)
        if not name.startswith(".") and os.path.isdir(os.path.join(target, name))
    ]
    parent = os.path.dirname(target) if target != os.path.dirname(target) else None
    return {
        "path": target,
        "parent": parent,
        "is_git_repo": os.path.exists(os.path.join(target, ".git")),
        "entries": entries,
    }


def reveal(path):
    """그 경로를 서버가 도는 컴퓨터의 파일 탐색기에 띄운다.

    note 에 적어 둔 경로를 눌러 여는 데 쓴다. 브라우저는 file:// 링크로 탐색기를
    띄울 수 없다(보안) — 그래서 화면은 경로만 보내고, 띄우는 것은 서버가 한다.
    """
    # 빈 경로를 그냥 흘리면 realpath 가 현재 디렉토리로 바꿔 엉뚱한 창이 뜬다
    if not path:
        raise Validation("경로가 필요함")
    target = os.path.realpath(os.path.expanduser(path))
    if not os.path.exists(target):
        raise Validation(f"없는 경로: {target}")
    command = reveal_command(target)
    try:
        # 종료 코드는 안 본다 — explorer.exe 는 제대로 띄워도 1 을 준다.
        # 창만 띄우고 바로 빠지는 명령들이라 기다려도 금방 끝난다
        subprocess.run(command, capture_output=True, timeout=REVEAL_TIMEOUT_SEC, check=False)
    except OSError as error:
        # 띄울 프로그램 자체가 없는 환경(GUI 없는 리눅스 등). 경로는 멀쩡하다
        raise Validation(f"탐색기를 띄우지 못함: {command[0]} ({error})") from error
    except subprocess.TimeoutExpired as error:
        raise Validation(f"탐색기가 응답하지 않음: {command[0]}") from error
    return {"path": target, "command": command}


def detect_system():
    """탐색기를 띄우는 방법이 갈리는 세 갈래 — mac · WSL · 그 밖의 리눅스"""
    if sys.platform == DARWIN:
        return DARWIN
    if "microsoft" in platform.uname().release.lower():
        return WSL
    return LINUX


def reveal_command(target, system=None):
    """경로 하나를 탐색기에 띄우는 명령. 파일이면 그 파일이 보이는 자리까지 간다"""
    system = system or detect_system()
    if system == DARWIN:
        return ["open", "-R", target]  # -R: 그 파일을 고른 채로 Finder 를 띄운다
    if system == WSL:
        windows_path = _windows_path(target)
        # 폴더는 그냥 열고, 파일은 /select 로 골라 준다
        if os.path.isfile(target):
            return ["explorer.exe", f"/select,{windows_path}"]
        return ["explorer.exe", windows_path]
    # 그 밖의 리눅스: 파일 하나를 지목하는 표준 방법이 없어 담긴 폴더를 연다
    return ["xdg-open", target if os.path.isdir(target) else os.path.dirname(target)]


def _windows_path(target):
    """WSL 경로를 윈도우 표기로. 변환이 안 되면 원래 경로를 그대로 넘긴다"""
    done = subprocess.run(["wslpath", "-w", target], capture_output=True, text=True)
    return done.stdout.strip() or target
