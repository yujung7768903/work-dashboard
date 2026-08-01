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

# 세션 팝업의 최근 대화. 원문은 DB 가 아니라 Claude Code 의 transcript jsonl 에만 있다
TRANSCRIPT_ROOT = os.path.expanduser("~/.claude/projects")
TRANSCRIPT_TAIL_BYTES = 512 * 1024
TRANSCRIPT_MAX_TAIL_BYTES = 8 * 1024 * 1024  # 발화가 안 잡히면 여기까지 넓혀가며 다시 읽음
TRANSCRIPT_MAX_MESSAGES = 10
TRANSCRIPT_MAX_CHARS = 400

# 초기 설정(온보딩). 히스토리 전문은 수백 MB 라 세션에 넣을 수 없으므로 CLI 가 먼저 압축한다.
# 세션이 무엇에 관한 것인지는 첫 지시에 거의 다 들어 있어 앞 조각만 읽으면 된다
HISTORY_HEAD_BYTES = 64 * 1024
HISTORY_FIRST_PROMPT_CHARS = 200
HISTORY_DAY_CHOICES = (7, 14)
# 세션 2건 이하 묶음은 워크스페이스로 만들지 않는다 — 확인 트리가 검수 가능한 크기를 넘으면
# 사용자는 읽지 않고 승인하게 되고, 그때부터 이 기능은 쓰레기를 만드는 장치가 된다.
# 묶는 것도 하한선을 적용하는 것도 주입 블록을 받은 Claude 가 한다 (의미 판단이라 코드가 못 함)
ONBOARDING_MIN_SESSIONS = 3
ONBOARDING_DECLINED_FLAG = "onboarding_declined"

# 대시보드에서 세션을 워크스페이스로 분류할 때 자동으로 만드는 할일.
# 그 자리에는 Claude 가 없어 의미 판단을 할 수 없으므로 지시 원문에서 뽑을 수 있는 만큼만 만든다
AUTO_TODO_TITLE_CHARS = 60
AUTO_TODO_NOTE_PROMPTS = 5  # note 에 싣는 지시 건수. 뒤로 갈수록 곁가지라 앞쪽만
AUTO_TODO_MAX_SUBTASKS = 8
AUTO_TODO_MIN_SUBTASKS = 2  # 1개면 할일과 같은 말이라 쪼갤 이유가 없다
AUTO_TODO_NOTE_HEAD = "(자동) 세션 분류 때 지시 원문에서 만든 할일. 진행하며 다듬는다."
# 요약은 뒷일로 돌리므로 할일이 만들어지는 순간의 제목은 늘 지시 첫 문장이다. 그 사실을
# note 한 줄로 남기고, 요약이 붙으면 그 줄을 지운다 — 남아 있으면 '손봐야 할 제목' 표시가 된다.
# 컬럼을 늘리지 않고 보드·팝업이 같은 판단(todos.needs_title)을 쓰게 하려고 note 에 둔다
AUTO_TODO_NOTE_RAW_TITLE = "제목: 요약이 붙지 않아 지시 첫 문장을 그대로 씀"

# 제목 요약. 한국어 문장을 규칙으로 줄이면 "…보이는데, 너무 길어져서" 같은 군더더기가 남는다.
# 요약은 의미 판단이라 설치된 claude CLI 에 맡기고, 실패하면 첫 문장을 그대로 쓴다
SUMMARY_MODEL = "claude-haiku-4-5-20251001"  # 제목 한 줄이라 가장 싼 모델로 충분
# CLI 기동만 7~8초이고, 다른 claude 프로세스와 겹치면 20초를 넘긴 적도 있다. 요약은 뒷일로
# 도는 뒤라 아무도 기다리지 않으므로 넉넉히 준다 — 짧게 잡아 실패하면 제목이 첫 문장으로 남는다
SUMMARY_TIMEOUT_SEC = 60
SUMMARY_MAX_CHARS = 40  # 이보다 길면 요약이 아니라 설명이므로 버린다

# 사용량. 한도 %는 statusline 페이로드에만 실려오는 값이라 파일에서 주워온다
# (훅 페이로드에는 rate_limits 가 없다). token-optimizer statusline 이 떨어뜨리는 사이드카.
RATE_LIMITS_PATH = os.path.expanduser("~/.claude/token-optimizer/rate-limits.json")
# 같은 값이 Claude Code 가 캐시하는 이 파일에도 있고, 그쪽에는 계정 uuid 가 붙어 온다.
# 계정을 초기화 시각으로 추론하는 대신 못박기 위해 같이 읽는다. 이 파일에는 계정 설정
# 전부가 들어 있으므로 사용량 키 하나만 꺼내고 다른 내용은 읽지도 반환하지도 않는다
CLAUDE_CONFIG_PATH = os.path.expanduser("~/.claude.json")
USAGE_CACHE_KEY = "cachedUsageUtilization"
# 플랜 이름도 이 파일의 계정 블록에서 온다. 예전에는 .credentials.json 에 있었는데
# 로그인 방식에 따라 그 키가 사라져(키체인으로 옮겨감) 양쪽을 다 본다
CONFIG_ACCOUNT_KEY = "oauthAccount"
CONFIG_TIER_KEY = "userRateLimitTier"  # 한도를 정하는 티어. seatTier 는 좌석 등급이라 다름
# 두 소스의 초기화 시각은 1초 어긋난다 — 한쪽은 :59.66 을 그대로, 다른 쪽은 정시로
# 반올림한 값을 준다. 같은 창인지 보려면 초 단위 오차를 허용해야 한다
RESET_MATCH_SECONDS = 5
CREDENTIALS_PATH = os.path.expanduser("~/.claude/.credentials.json")
COST_LOG_PATH = os.path.expanduser("~/.claude/metrics/costs.jsonl")
CREDENTIALS_TIER_PREFIX = "default_claude_"
# statusline 은 세션이 돌 때만 다시 그려진다. 조용한 동안 값이 낡는 건 정상이므로
# 15분을 넘으면 "지금 값"으로 읽히지 않게 낡음 표시만 한다
USAGE_STALE_SECONDS = 900
USAGE_SAMPLE_MIN_GAP_MS = 60_000  # % 추이 해상도 1분. 더 촘촘한 statusline 갱신은 버린다
# 주차 비교가 거슬러 볼 수 있는 과거는 이 보존 기간이 정한다 — 90일이면 12주차까지.
# 1분 해상도라 하루 최대 1440줄, 90일에 13만 줄로 sqlite 에 부담이 되는 크기가 아니다
USAGE_SAMPLE_RETENTION_DAYS = 90
USAGE_SAMPLE_WINDOW_HOURS = 24  # % 추이로 내려보내는 구간
USAGE_SAMPLE_BUCKET_MS = 300_000  # 5분 버킷. 폴링마다 원본 수천 줄을 실어보내지 않기 위함
USAGE_TREND_DAYS = 14
# 주간 창 하나의 길이. 같은 계정의 다음 창은 정확히 이만큼 뒤에 열리므로, 이 값으로
# 나눈 나머지가 계정을 가르는 열쇠가 된다 (계정이 둘이면 주간 창도 둘이 동시에 돈다)
WEEK_SECONDS = 604_800
USAGE_WEEK_LIMIT = 12  # 주차 비교에 세우는 막대 수. 보존 기간(90일)이 실질 상한
# 이보다 적게 잡힌 트랙은 계정으로 보지 않는다. 사이드카에는 정시가 아닌 초기화 시각이
# 한두 줄 섞여 들어오는데, 그걸 계정으로 세우면 주차 비교에 한 칸짜리 유령 트랙이 생긴다
USAGE_TRACK_MIN_SAMPLES = 3
USAGE_WARN_PCT = 70
USAGE_CRITICAL_PCT = 90
# /usage 가 보여주는 창 중 사이드카에 남는 두 개. 나머지는 MISSING_WINDOW_LABELS 로 알린다
USAGE_WINDOWS = (("five_hour", "현재 세션 (5시간)"), ("seven_day", "이번 주 (전체 모델)"))
MISSING_WINDOW_LABELS = ("이번 주 (Sonnet 전용)", "모델별 주간 창")
TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")
COST_FIELD = "estimated_cost_usd"
MODEL_FAMILIES = (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable"))
MODEL_FAMILY_OTHER = "기타"
