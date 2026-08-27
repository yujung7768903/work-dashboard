"""프로젝트 전역 상수. 매직넘버는 전부 여기로 모음"""
import os

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9080
BUSY_TIMEOUT_MS = 5000

# start.sh·stop.sh·restart.sh 를 실제로 실행해 검사하는 테스트가 쓰는 대역.
# 이 대역을 듣는 서버는 화면(워크트리 탭·상태줄·자율 수행 패널)에 그리지 않는다
TEST_SERVER_PORTS = range(9900, 10000)

DEFAULT_DB_PATH = os.path.expanduser("~/.claude/work-dashboard/dash.db")
DB_PATH_ENV = "WORK_DASHBOARD_DB"

UNASSIGNED_LABEL = "미분류"
SEED_CATEGORIES = ("개발", "운영", "장애 대응", "개발환경 개선", "스킬 개발", "프로세스 개선")

# 화면 언어. 문구는 코드가 아니라 static/lang/<코드>.json 에 키-값으로 모여 있고,
# 네 파일이 서로 같은 자격이다. 코드 목록이 화면과 갈라지거나 번역이 빠지면
# tests/test_language.py 가 잡는다.
# 기본값·폴백은 영어다 — 이 대시보드를 공개로 열 것이므로, 설정을 못 읽거나 번역이
# 빠졌을 때 처음 보는 사람이 읽을 수 있는 쪽으로 떨어져야 한다.
# CLI 출력·훅 주입 블록은 아직 한국어 고정 — 읽는 쪽이 Claude 라 옮길 이유가 없다
LANGUAGES = ("en", "ko", "ja", "zh")
DEFAULT_LANGUAGE = LANGUAGES[0]
LANGUAGE_KEY = "language"  # meta 테이블 키

# 카테고리 색은 sort_order 로 팔레트에서 자동 배정하고 이후 사용자가 바꿀 수 있음.
# 미분류는 팔레트 밖의 옅은 회색 (CSS .group 의 --cat 기본값과 같은 값)
CATEGORY_PALETTE = (
    "#7c6cf0", "#2aa77a", "#e0574a", "#2d8bdf",
    "#e08a2d", "#c85fb0", "#4aa3a3", "#8a9a2d",
)
COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"

TODO_STATUSES = ("todo", "doing", "done")
WORKSPACE_STATUSES = ("active", "inactive", "done")
STATUS_TODO, STATUS_DOING, STATUS_DONE = TODO_STATUSES
WORKSPACE_ACTIVE = WORKSPACE_STATUSES[0]

ALLOWED_STATIC_SUFFIXES = (".html", ".css", ".js", ".json")  # .json 은 화면 문구 사전
FIRST_SORT_ORDER = 1

# 여러 자리에서 같은 말을 해야 하는 사용자용 문구. 화면에는 alert 로, CLI 에는
# 그대로 찍히므로 설명이 아니라 사용자에게 보내는 문장으로 쓴다
# 분류 대상 누락: 할일 생성·세션 분류 세 곳
SCOPE_REQUIRED_MSG = "카테고리나 워크스페이스 중 하나를 선택해 주세요"

# 세션이 띄운 하위 프로세스에 실려오는 자기 세션 id. 훅 stdin 의 session_id 와 같은 값이라
# CLI 가 이걸로 자기 세션을 안다 — 모델이 주입 블록의 UUID 를 옮겨 적지 않아도 된다
SESSION_ID_ENV = "CLAUDE_CODE_SESSION_ID"
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

# 착수 조건 작성 안내. CLI(--precondition 도움말)와 추가 팝업이 같은 문구를 쓴다 —
# 두 곳에서 다르게 설명하면 어느 쪽 규약이 맞는지 알 수 없다.
# 세션에는 첫 줄만 주입되므로(session_link) 판정 문장이 첫 줄에 와야 한다
PRECONDITION_HINT = (
    "참/거짓이 갈리는 한 문장을 한 줄에 하나씩 쓴다."
    " 다른 할일이 조건이면 #id 로 적고, 명령으로 확인되면 다음 줄에 '확인: <명령>'."
    " #id 조건은 그 할일이 done 이 되면 저절로 풀린다."
    " 코드가 판정할 수 없는 문장이 하나라도 있으면 자율 수행 후보에서 빠진다"
)
PRECONDITION_EXAMPLE = "#57 이 done 일 것\n확인: git -C ~/work/work-dashboard status --short"

# 대시보드에서 세션을 워크스페이스로 분류할 때 자동으로 만드는 할일.
# 그 자리에는 Claude 가 없어 의미 판단을 할 수 없으므로 지시 원문에서 뽑을 수 있는 만큼만 만든다
AUTO_TODO_TITLE_CHARS = 60
AUTO_TODO_NOTE_PROMPTS = 5  # note 에 싣는 지시 건수. 뒤로 갈수록 곁가지라 앞쪽만
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
# Google Tasks 양방향 동기화. google-api-python-client 를 쓰면 이 프로젝트의 첫 외부
# 의존성이 되고 전이 패키지가 열 개 넘게 딸려온다. 우리가 쓰는 엔드포인트는 다섯 개뿐이라
# urllib 로 직접 치는 쪽이 싸다
GTASKS_CONFIG_PATH = os.path.expanduser("~/.claude/work-dashboard/gtasks.json")
# 최초 인증 1회에만 쓰는 값. 플래그로 넘기면 셸 히스토리에 secret 이 남아 환경변수를 먼저 본다
GTASKS_CLIENT_ID_ENV = "GTASKS_CLIENT_ID"
GTASKS_CLIENT_SECRET_ENV = "GTASKS_CLIENT_SECRET"
GTASKS_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GTASKS_TOKEN_URL = "https://oauth2.googleapis.com/token"
GTASKS_API_ROOT = "https://tasks.googleapis.com/tasks/v1"
GTASKS_SCOPE = "https://www.googleapis.com/auth/tasks"
GTASKS_TIMEOUT_SEC = 20
GTASKS_PAGE_MAX = 100  # Tasks API 가 한 번에 주는 최대치. 기본값 20 이라 명시해야 함
GTASKS_TOKEN_MARGIN_SEC = 60  # 만료 직전에 쓰다 401 나는 걸 피하려고 미리 갱신
GTASKS_SEEN_KEY = "gtasks_seen_ids"
GTASKS_STATUS_DONE = "completed"
GTASKS_STATUS_TODO = "needsAction"
GTASKS_NOTES_MAX = 8000  # 구글 상한은 8192. 잘라 보내지 않으면 호출 전체가 400 으로 죽는다
GTASKS_UNTITLED = "(제목 없음)"
# 로컬 인증 콜백. 데스크톱 OAuth 클라이언트는 127.0.0.1 이면 포트를 안 가린다
GTASKS_AUTH_HOST = "127.0.0.1"
GTASKS_AUTH_TIMEOUT_SEC = 300
# 문제가 생겨도 연동을 끄지 않는다 — 껐다 켜는 건 사람 몫이고, 화면은 사유만 보여준다.
# 와이파이가 한 번 끊겼다고 설정이 꺼지면 사용자가 그걸 눈치채지 못한 채 며칠을 보낸다
GTASKS_ERROR_NO_AUTH = "연결 안 됨"
GTASKS_ERROR_EXPIRED = "로그인 만료"
# 인증 전에 동기화 쪽을 건드리면 load_config 의 원문(파일 경로 + CLI 명령)이 그대로 뜬다.
# 화면에는 다음에 누를 것을 알려준다 — 경로를 읽고 터미널을 열라는 뜻이 아니다
GTASKS_NEED_CONNECT = "아래 '연결하기' 버튼으로 구글 태스크와 연동을 먼저 진행해 주세요"
# 자동 실행이 걸려 있는지 launchd·crontab 에서 찾을 때 쓰는 표식
GTASKS_SYNC_CMD = "gtasks-sync"
SCHEDULE_TIMEOUT_SEC = 2
SECONDS_PER_MINUTE = 60
# app/services/usage.py 의 str.removeprefix 가 3.9 에서 들어왔다 — 이 프로젝트의 하한
PYTHON_MIN = "3.9"
# 같은 3.9 라도 ssl 없이 빌드되면 urllib 에 https 핸들러가 안 붙어
# "unknown url type: https" 라는, 원인을 짐작할 수 없는 문구로 끝난다
GTASKS_NO_SSL = (
    f"이 Python 은 HTTPS 를 쓸 수 없습니다 (ssl 모듈 없음). Python {PYTHON_MIN} 이상이어도"
    ' 빌드에 따라 빠질 수 있습니다 — python3 -c "import ssl" 로 확인하고'
    " 통과하는 Python 으로 서버를 다시 띄우세요"
)
GTASKS_NO_BROWSER = "브라우저를 열 수 없습니다. 아래 주소를 직접 열어 승인하세요:"

TOKEN_FIELDS = ("input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens")
COST_FIELD = "estimated_cost_usd"
MODEL_FAMILIES = (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("fable", "Fable"))
MODEL_FAMILY_OTHER = "Other"  # 화면이 이 이름만 사전에서 꺼내 옮긴다 (usage.modelOther)

# ④ 자율 실행. 사람이 자리를 비운 사이 할일 1건씩 `claude --bg` 잡으로 돌린다.
# 대상은 두 겹으로 좁힌다 — 사람이 붙인 라벨과, 코드가 판정할 수 없는 조건의 부재.
AUTORUN_LABEL = "auto"  # 이 라벨이 붙은 할일만 후보. 자율 실행 허가는 사람이 라벨로 준다
AUTORUN_MODEL = "claude-sonnet-5"  # 모델은 상수. 성공률 학습·자동 선택은 하지 않는다
AUTORUN_MAX_CONCURRENT = 1  # 사용량 창을 나눠 쓰면 둘 다 리밋에 걸리고 diff 가 섞인다
AUTORUN_CANDIDATE_LIMIT = 5  # 자율 수행 화면 후보 줄 수. 더 보여줘도 다음에 돌 것은 맨 위 하나다
AUTORUN_FAIL_LIMIT = 2  # 같은 할일이 이만큼 연속 실패하면 막고 다음 할일로
AUTORUN_BLOCKED_STREAK_LIMIT = 3  # blocked 가 이만큼 연속이면 autorun 자체를 끈다
# review(검토 대기)가 성공한 잡의 첫 결과다. 다 끝냈고 확인할 것도 불분명한 것도 없을
# 때만 자율 세션이 커밋하므로, 잡이 끝난 시점의 그 작업은 '끝난 것'이 아니라 '사람이 보고
# 병합을 판정할 것'이다.
# done 은 사람이 검토 대기 배지를 눌러 내렸을 때만 붙는다 — 진행 중과 검토 대기를 같은
# 배지로 뭉개면 사람이 무엇을 봐야 하는지 목록에서 알 수 없다
# requested(요청)는 blocked 와 달리 실패가 아니라 세션이 스스로 멈춘 것이다 — 기획이
# 비었거나, 방향이 여럿인데 note 에 안 정해져 있거나, 토큰·Jira·문서 위치가 없어서
# 추측 대신 사람 판단을 기다린다. blocked 처럼 다음 tick 후보에서 빠지지만 실패 횟수에는
# 안 세고 blocked_streak 도 안 건드린다 — 오류가 아니라 의도적인 정지라서다
AUTORUN_OUTCOMES = ("done", "review", "failed", "blocked", "requested")
OUTCOME_DONE, OUTCOME_REVIEW, OUTCOME_FAILED, OUTCOME_BLOCKED, OUTCOME_REQUESTED = (
    AUTORUN_OUTCOMES
)
# --bg 잡의 상태 파일. 이 값들이면 잡이 끝난 것으로 보고 실행 기록을 닫는다.
# blocked(리밋)는 열어 둔다 — resume-limited-jobs.py 가 다시 밀어 준다
AUTORUN_JOBS_ROOT = os.path.expanduser("~/.claude/jobs")
AUTORUN_JOB_TERMINAL = ("done", "failed", "stopped")
AUTORUN_CLAUDE_BIN = os.path.expanduser("~/.local/bin/claude")
AUTORUN_LAUNCH_TIMEOUT_SEC = 180  # --bg 는 띄우자마자 돌아오므로 기동 시간만 덮는다
# 검토 대기(review) 중인 할일에 새 잡을 또 띄우면 확인 전에 diff 가 두 벌 생긴다.
# 할일 상태 수정과 할일 케밥의 "시작" 둘 다 이 문구로 막는다
REVIEW_LOCKED_MSG = "자율 수행 검토 대기 중입니다. 자율 수행 패널에서 확인해 주세요"
# 병합 전 테스트. 이 저장소는 40초대지만 다른 저장소의 통합 테스트까지 덮는 넉넉한 상한
MERGE_TEST_TIMEOUT_SEC = 600
