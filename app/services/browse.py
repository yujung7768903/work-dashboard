"""로컬 파일시스템 폴더 탐색. 할일 케밥의 "시작" 이 작업 위치를 못 정했을 때
화면이 사람에게 물어 받는 경로 선택기가 여기를 부른다.

서버가 도는 컴퓨터의 파일시스템을 그대로 읽을 뿐이다 — 이 대시보드는 1인용·인증 없이
로컬에서만 돈다는 전제(README)라, 파일 하나 더 읽는다고 새 위험이 생기지 않는다.
"""
import os

from app.errors import Validation

DEFAULT_ROOT = os.path.expanduser("~")


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
