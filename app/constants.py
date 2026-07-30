"""프로젝트 전역 상수. 매직넘버는 전부 여기로 모음"""
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9080
BUSY_TIMEOUT_MS = 5000

DEFAULT_DB_PATH = os.path.expanduser("~/.claude/work-dashboard/dash.db")
DB_PATH_ENV = "WORK_DASHBOARD_DB"

UNASSIGNED_LABEL = "미분류"
SEED_CATEGORIES = ("개발", "운영", "장애 대응", "개발환경 개선", "스킬 개발", "프로세스 개선")

# 카테고리 색은 sort_order 로 팔레트에서 자동 배정하고 이후 사용자가 바꿀 수 있음.
# 미분류는 팔레트 밖의 옅은 회색 (CSS .group 의 --cat 기본값과 같은 값)
CATEGORY_PALETTE = (
    "#7c6cf0", "#2aa77a", "#e0574a", "#2d8bdf",
    "#e08a2d", "#c85fb0", "#4aa3a3", "#8a9a2d",
)
SEED_CATEGORY_EMOJI = {
    "개발": "💻", "운영": "🛠️", "장애 대응": "🚨",
    "개발환경 개선": "⚙️", "스킬 개발": "🧩", "프로세스 개선": "📋",
}
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"
# ZWJ·변형선택자로 이어붙은 이모지가 10 코드포인트를 넘기도 해서 넉넉하게 잡음
EMOJI_MAX_CHARS = 16

TODO_STATUSES = ("todo", "doing", "done")
WORKSPACE_STATUSES = ("active", "paused", "done")
STATUS_TODO, STATUS_DOING, STATUS_DONE = TODO_STATUSES
WORKSPACE_ACTIVE = WORKSPACE_STATUSES[0]

ALLOWED_STATIC_SUFFIXES = (".html", ".css", ".js")
FIRST_SORT_ORDER = 1

SESSION_STATES = ("working", "idle", "ended")
STATE_WORKING, STATE_IDLE, STATE_ENDED = SESSION_STATES
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
STALE_IDLE_HOURS = 24
ENDED_RETENTION_DAYS = 7
LAST_PROMPT_MAX_CHARS = 120
POLL_INTERVAL_MS = 2000
JIRA_PATTERN = r"[A-Za-z]+-[0-9]+"
