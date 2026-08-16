#!/usr/bin/env bash
# Claude Code 훅을 ~/.claude/settings.json 에 등록한다.
#   ./setup.sh   → 훅 8개 등록. 이미 있으면 경로만 갱신하고, 같으면 그대로 둔다
# 워크트리 안에서 실행해도 메인 체크아웃 경로를 등록한다 — 워크트리는 병합 뒤 지워진다.
# worktree_serve.py 는 이 저장소의 .claude/settings.json 이 들고 있어 여기서 다루지 않는다.
# 서버를 띄우는 것은 ./start.sh.
set -euo pipefail
cd "$(dirname "$0")"

# 워크트리에서 실행돼도 .git 본체가 있는 곳 = 메인 체크아웃
common=$(git rev-parse --git-common-dir 2>/dev/null || echo .git)
main=$(cd "$(dirname "$common")" && pwd -P)

python3 - "$main" <<'PY'
import json
import os
import shutil
import sys

repo = sys.argv[1]
path = os.path.expanduser("~/.claude/settings.json")

# (이벤트, matcher, 훅 스크립트와 인자, timeout)
HOOKS = (
    ("SessionStart", "", "dash_hook.py SessionStart", 2),
    ("UserPromptSubmit", "", "dash_hook.py UserPromptSubmit", 2),
    ("Stop", "", "dash_hook.py Stop", 2),
    ("SessionEnd", "", "dash_hook.py SessionEnd", 2),
    ("UserPromptSubmit", "", "stale_base.py", 10),
    ("PreToolUse", "Write|Edit|NotebookEdit", "worktree_guard.py", 10),
    ("PreToolUse", "Bash", "commit_scope_guard.py", 10),
    ("PostToolUse", "Write|Edit|NotebookEdit", "md_lint.py", 15),
)


def registered(groups, tail):
    """경로가 달라도 같은 훅이면 찾아낸다 — 저장소를 옮겼을 때 두 번 등록되지 않게"""
    for group in groups:
        for hook in group.get("hooks", []):
            if hook.get("command", "").endswith(tail):
                return hook
    return None


def group_for(groups, matcher):
    for group in groups:
        if group.get("matcher", "") == matcher:
            return group
    group = {"matcher": matcher, "hooks": []}
    groups.append(group)
    return group


settings = {}
if os.path.exists(path):
    with open(path) as handle:
        try:
            settings = json.load(handle)
        except ValueError as error:
            sys.exit(f"{path} 를 읽을 수 없다 ({error}). 고친 뒤 다시 실행한다")

events = settings.setdefault("hooks", {})
if not isinstance(events, dict):
    sys.exit(f"{path} 의 hooks 가 이벤트별 객체가 아니다. 직접 확인한 뒤 다시 실행한다")

added, moved = [], []
for event, matcher, spec, timeout in HOOKS:
    tail = f"hooks/{spec}"
    command = f"python3 {repo}/{tail}"
    groups = events.setdefault(event, [])
    hook = registered(groups, tail)
    if hook is not None:
        if hook.get("command") != command:
            hook["command"] = command
            moved.append(f"{event} · {spec}")
        continue
    group_for(groups, matcher).setdefault("hooks", []).append(
        {"type": "command", "command": command, "timeout": timeout}
    )
    added.append(f"{event} · {spec}")

if not added and not moved:
    print(f"훅 {len(HOOKS)}개가 이미 {repo} 를 가리킨다. 바뀐 것 없음")
else:
    backup = f"{path}.bak"
    if os.path.exists(path):
        shutil.copy2(path, backup)
    else:
        backup = None
        os.makedirs(os.path.dirname(path), exist_ok=True)
    temp = f"{path}.tmp"
    with open(temp, "w") as handle:
        json.dump(settings, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(temp, path)
    for name in added:
        print(f"등록      {name}")
    for name in moved:
        print(f"경로 갱신  {name}")
    print(f"{path} 저장" + (f" · 이전 파일은 {backup}" if backup else ""))
PY

cat <<'EOF'

다음 단계
  1. ./start.sh — 서버를 띄우고 http://127.0.0.1:9080 을 연다
  2. Claude Code 세션을 새로 연다. 워크스페이스가 하나도 없으면 초기 설정 안내가
     주입되고, Claude 가 ~/.claude/projects 의 과거 세션을 훑어 워크스페이스와
     할일을 제안한다. 안 쓸 거면 python3 dash.py onboard --skip
  3. 상태줄과 자율 실행은 선택이다 — README 의 Status line · Autonomous runs 참고
EOF
