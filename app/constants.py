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
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"

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

# 사용량. 한도 %는 statusline 페이로드에만 실려오는 값이라 파일에서 주워온다
# (훅 페이로드에는 rate_limits 가 없다). token-optimizer statusline 이 떨어뜨리는 사이드카.
RATE_LIMITS_PATH = os.path.expanduser("~/.claude/token-optimizer/rate-limits.json")
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
COST_LOG_PATH = os.path.expanduser("~/.claude/metrics/costs.jsonl")
CREDENTIALS_TIER_PREFIX = "default_claude_"
# statusline 은 세션이 돌 때만 다시 그려진다. 조용한 동안 값이 낡는 건 정상이므로
# 15분을 넘으면 "지금 값"으로 읽히지 않게 낡음 표시만 한다
USAGE_STALE_SECONDS = 900
USAGE_SAMPLE_MIN_GAP_MS = 60_000  # % 추이 해상도 1분. 더 촘촘한 statusline 갱신은 버린다
USAGE_SAMPLE_RETENTION_DAYS = 30
USAGE_SAMPLE_WINDOW_HOURS = 24  # % 추이로 내려보내는 구간
USAGE_SAMPLE_BUCKET_MS = 300_000  # 5분 버킷. 폴링마다 원본 수천 줄을 실어보내지 않기 위함
USAGE_TREND_DAYS = 14
USAGE_WARN_PCT = 70
USAGE_CRITICAL_PCT = 90
# /usage 가 보여주는 창 중 사이드카에 남는 두 개. 나머지는 MISSING_WINDOW_LABELS 로 알린다
USAGE_WINDOWS = (("five_hour", "현재 세션 (5시간)"), ("seven_day", "이번 주 (전체 모델)"))
MISSING_WINDOW_LABELS = ("이번 주 (Sonnet 전용)", "모델별 주간 창")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")
COST_FIELD = "estimated_cost_usd"
MODEL_FAMILIES = (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable"))
MODEL_FAMILY_OTHER = "기타"
