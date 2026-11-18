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

# review(확인 대기) = 작업은 끝났고 사람의 확인만 남은 것. done 이 아니므로 보드 진행률·
# 구글 태스크에서는 열린 할일로 남고, 할 일이 아니므로 다음 할일·자율 수행 후보에서는 빠진다
TODO_STATUSES = ("todo", "doing", "review", "done")
WORKSPACE_STATUSES = ("active", "inactive", "done")
STATUS_TODO, STATUS_DOING, STATUS_REVIEW, STATUS_DONE = TODO_STATUSES
# 손을 대야 하는(착수할 수 있는) 상태. review 는 손이 아니라 눈이 남은 것이라 뺀다
WORKABLE_STATUSES = (STATUS_TODO, STATUS_DOING)
WORKSPACE_ACTIVE = WORKSPACE_STATUSES[0]

ALLOWED_STATIC_SUFFIXES = (".html", ".css", ".js", ".json")  # .json 은 화면 문구 사전
FIRST_SORT_ORDER = 1

# 여러 자리에서 같은 말을 해야 하는 사용자용 문구. 화면에는 alert 로, CLI 에는
# 그대로 찍히므로 설명이 아니라 사용자에게 보내는 문장으로 쓴다
# 분류 대상 누락: 할일 생성·세션 분류 세 곳
SCOPE_REQUIRED_MSG = "카테고리나 워크스페이스 중 하나를 선택해 주세요"
PRIORITY_INVALID_MSG = "우선순위는 1 이상 정수로 입력해 주세요"
# 트리(상위 할일). 화면 alert 와 CLI 가 같은 문장을 쓴다
PARENT_CYCLE_MSG = "자기 자신이나 하위 할일을 상위로 지정할 수 없습니다"
PARENT_INVALID_MSG = "상위 할일은 할일 번호로 지정해 주세요"

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
# handover(인계)는 도는 잡에 사람이 프롬프트를 넣어 그 세션을 이어받은 것이다. 실행 기록만
# 닫고 autorun 은 계속 돈다 — 세션 하나를 사람이 맡았다고 다른 할일까지 멈출 이유가 없다.
# 실패도 성공도 아니라 실패 횟수에 안 세고, 사람이 이미 그 세션에 있으니 주의 목록에도 안 든다
AUTORUN_OUTCOMES = ("done", "review", "failed", "blocked", "requested", "handover")
(
    OUTCOME_DONE,
    OUTCOME_REVIEW,
    OUTCOME_FAILED,
    OUTCOME_BLOCKED,
    OUTCOME_REQUESTED,
    OUTCOME_HANDOVER,
) = AUTORUN_OUTCOMES
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

# ⑥ 방치된 doing 판정. 오래 손대지 않은 doing 을 모델이 근거(note·세션·트랜스크립트·
# 워크트리 병합 여부)로 읽고 끝났는지·무효인지·대기로 돌릴지 정한다. 규칙으로 판정하지
# 않는 이유 — "끝났다"는 흔적이 커밋·문서·대화 중 어디에 남는지가 할일마다 달라서다.
# 실측(2026-11-05): doing 84건 중 62건이 14일 이상 방치, 평균 40일
STALE_JUDGE_IDLE_DAYS = 14  # 이보다 오래 updated_at 이 안 움직인 doing 만 본다
STALE_JUDGE_REPEAT_DAYS = 14  # 한 번 keep 으로 본 할일은 이만큼 지나야 다시 본다
STALE_JUDGE_BATCH = 10  # 하루 한 번 도는 크론이라 모델 호출 수를 이만큼으로 막는다
STALE_JUDGE_MODEL = "claude-sonnet-5"
STALE_JUDGE_TIMEOUT_SEC = 180
# 이 값 밑이면 상태를 안 바꾸고 keep 으로 기록만 한다 — 틀리면 끝난 척하는 할일이 남는다
STALE_JUDGE_MIN_CONFIDENCE = 0.7
STALE_JUDGE_VERDICTS = ("done", "invalid", "todo", "keep")
(
    VERDICT_DONE,
    VERDICT_INVALID,
    VERDICT_TODO,
    VERDICT_KEEP,
) = STALE_JUDGE_VERDICTS
# note 에 남기는 머리말. 사람이 보드에서 왜 바뀌었는지 읽고, 틀렸으면 되돌릴 수 있어야 한다
STALE_JUDGE_NOTE_MARK = "[자동 판정"
STALE_JUDGE_LABELS = {
    VERDICT_DONE: "완료로 닫음",
    VERDICT_INVALID: "무효로 닫음",
    VERDICT_TODO: "대기로 되돌림",
}
STALE_JUDGE_SESSION_LIMIT = 3  # 근거에 넣는 세션 수. 최근 것부터
STALE_JUDGE_TRANSCRIPT_MESSAGES = 8
STALE_JUDGE_TEXT_CHARS = 400  # 발화·note 한 조각의 길이 상한. 프롬프트를 수천 자로 막는다
STALE_JUDGE_NOTE_CHARS = 1500
STALE_JUDGE_SIBLING_LIMIT = 15  # 같은 워크스페이스의 다른 할일. 대체·중복 판단 근거

# 매니저 탭. 매니저 레포 위치 — 보조 세션 목록(manager.py 보조 --json)·결정 대기(state/manager.db,
# 읽기 전용)·주기 점검 훅 상수를 여기서 읽는다
MANAGER_HOME_ENV = "WORK_DASHBOARD_MANAGER_HOME"
MANAGER_HOME_DEFAULT = os.path.expanduser("~/work/manager")
# manager.py 보조 는 claude agents --json 을 부른다(수 초). 그보다 넉넉히
MANAGER_HELPERS_TIMEOUT_SEC = 45
# 결정에 화면에서 답하기(app/services/decision_answer.py). task list·show 는 DB 만 읽어 1초 안에 끝난다
MANAGER_TASK_TIMEOUT_SEC = 15
# answer-ui 는 죽은 원 세션을 되살려 도착을 기다리느라 최대 90초 걸린다(매니저 answer-ui --help). 그보다 넉넉히
MANAGER_ANSWER_TIMEOUT_SEC = 180
# 권한 요청에 화면에서 답하기(app/services/permission_answer.py). 매니저 permission_gate 가 결정 파일을 기다리는
# 시간(MANAGER_GATE_TIMEOUT 기본 540초)과, 그 훅을 Claude Code 가 끊는 시간(settings.json 훅 timeout 600초).
# 요청 파일이 끊는 시간보다 오래 남아 있으면 기다리던 훅은 이미 없다 — 답해도 받을 쪽이 없다
MANAGER_GATE_WAIT_SEC = 540
MANAGER_GATE_HOOK_TIMEOUT_SEC = 600
# 매니저 탭 도구 목록. claude mcp list 는 stdio 서버(디스코드 봇 포함)를 실제로 띄워 보므로 한 시간에 한 번만
TOOLS_CACHE_SEC = 3600
TOOLS_MCP_TIMEOUT_SEC = 90
TOOLS_CLI_TIMEOUT_SEC = 15

# ── 할일 관계 그래프 ─────────────────────────────────────────────────────
# 노드는 (종류, id) 쌍. 할일·세션은 제 테이블이 있고, 맥락·근거 문서는 graph_nodes 에 있다.
# id 는 모두 글자로 다룬다 — 세션 id 는 UUID, 문서 id 는 'jira:PFD-6350' 같은 정규화 키라서다.
# 관계는 edges 한 곳에 둔다. 수행만 예외 — session_todos 를 그대로 쓰고 graph_edges 뷰로 합친다
# (두 곳에 적으면 세션 연결·해제 경로마다 맞춰야 하고, 어긋나면 어느 쪽이 맞는지 모른다)
NODE_TODO, NODE_CONTEXT, NODE_DOC, NODE_SESSION = "todo", "context", "doc", "session"
NODE_KINDS = (NODE_TODO, NODE_CONTEXT, NODE_DOC, NODE_SESSION)
# 상위(parent)는 왜, 선행(precedes)은 언제. 근거(evidence)는 할일 → 문서, 수행(performs)은 세션 → 할일,
# 관련(related)은 위 어느 것도 아니지만 같은 질문을 다루는 둘 — 방향이 없어 작은 쪽을 출발로 둔다.
# 결과(result)는 세션 → 문서 — 그 세션이 만들거나 고친 것. 근거와 같은 문서 노드를 가리킬 수 있다
REL_PARENT, REL_PRECEDES, REL_EVIDENCE, REL_PERFORMS, REL_RELATED, REL_RESULT = (
    "parent", "precedes", "evidence", "performs", "related", "result",
)
RELATIONS = (REL_PARENT, REL_PRECEDES, REL_EVIDENCE, REL_PERFORMS, REL_RELATED, REL_RESULT)
# 순환을 막는 관계. 상위가 고리면 루트에서 닿지 않는 가지가 생기고, 선행이 고리면 아무것도 먼저 못 한다
ACYCLIC_RELATIONS = (REL_PARENT, REL_PRECEDES)
# 관계마다 허용하는 (출발, 도착) 종류. 맥락은 워크스페이스 아래 루트라 누구의 하위도 아니다.
# 수행은 session_todos 가 정본이라 여기 없다 — edges 에 직접 쓰지 않는다
RELATION_KINDS = {
    REL_PARENT: ((NODE_TODO, NODE_CONTEXT), (NODE_TODO,)),
    REL_PRECEDES: ((NODE_TODO,), (NODE_TODO,)),
    REL_EVIDENCE: ((NODE_TODO, NODE_CONTEXT), (NODE_DOC,)),
    REL_RELATED: ((NODE_TODO, NODE_CONTEXT), (NODE_TODO, NODE_CONTEXT)),
    REL_RESULT: ((NODE_SESSION,), (NODE_DOC,)),
}
# 상위의 기준 셋. 계기 = A 가 없었다면 B 를 이 시점에 시작했을까, 목적 = B 가 끝나면 A 완료에 직접
# 기여하나, 배경 = B 를 설명하려면 A 를 알아야 하나(가장 가까운 하나에만)
BASIS_TRIGGER, BASIS_PURPOSE, BASIS_BACKGROUND = "trigger", "purpose", "background"
PARENT_BASES = (BASIS_TRIGGER, BASIS_PURPOSE, BASIS_BACKGROUND)
# rejected 는 지우지 않고 남긴다 — 자동 제안이 같은 연결을 다시 만들지 않게 하려는 것이다
EDGE_CONFIRMED, EDGE_PROPOSED, EDGE_REJECTED = "confirmed", "proposed", "rejected"
EDGE_STATES = (EDGE_CONFIRMED, EDGE_PROPOSED, EDGE_REJECTED)
# 만든 주체. 자동 추출은 출처별로 나눠 둔다 — note 에서 키가 빠지면 note 출처 연결만 걷어낸다
BY_USER = "user"
BY_PARENT_COLUMN = "parent_id"  # todos.parent_id 와 짝을 이루는 연결. 이 열을 바꾸면 따라 바뀐다
# parent_id 와 짝인 연결을 만든 다른 주체 — 매니저 할일 이관(unify)과 매니저가 만든 단계(manager). parent_id 를 바꾸면
# 이것들도 parent_id 짝처럼 따라 바뀐다(옛 상위 연결이 남아 할일이 두 상위 아래 그려지지 않게)
BY_UNIFY = "unify"
BY_MANAGER = "manager"
PARENT_COLUMN_CREATORS = (BY_PARENT_COLUMN, BY_UNIFY, BY_MANAGER)
BY_NOTE = "auto:note"
BY_SHARED_DOC = "auto:shared-doc"
BY_REBUILD = "rebuild"
BY_SPAWN = "spawn"
BY_TRANSCRIPT = "auto:transcript"  # 세션 transcript 의 쓰기 호출·완료 보고에서 뽑은 결과
EDGE_CYCLE_MSG = "이 연결을 저장하면 순환이 생깁니다"
EDGE_KIND_MSG = "이 관계로 이을 수 없는 종류입니다"
EDGE_SELF_MSG = "자기 자신과는 이을 수 없습니다"
EDGE_BASIS_MSG = "상위 연결은 기준(계기·목적·배경)을 골라야 합니다"
EDGE_RELATION_MSG = "관계는 상위·선행·근거·관련·결과 중 하나여야 합니다"
EDGE_STATE_MSG = "연결 상태는 확정·제안·거절 중 하나여야 합니다"
CONTEXT_TITLE_MSG = "맥락 제목을 입력해 주세요"
# 관련 자동 연결은 같은 문서를 공유하는 할일 쌍마다 만든다. 이보다 많은 할일이 같은 문서를 가리키면
# 그 문서는 묶음(에픽·정기배포 페이지)이라 쌍을 다 만들면 선만 늘어난다 — 문서 노드로만 잇는다
SHARED_DOC_MAX_TODOS = 6

# 매니저 spawn 이 띄운 보조 세션의 할일. 보조 세션이 스스로 할일을 만들게 두었더니 11-11~16 비매니저 보조
# 99개 중 83개가 할일 없이 끝나 트리에서 맥락이 사라졌다 — 띄우는 쪽이 바로 만들어 수행으로 잇는다(결정 #180).
# 원래 세션 할일을 모르면 워크스페이스 없이 임시 카테고리로 만들고, 세션이 분류하면 그쪽으로 옮긴다
SPAWN_TODO_MARK = "(매니저 spawn)"
SPAWN_FALLBACK_CATEGORY = "분석/검토"  # 보조 세션 일은 조사·분석이 가장 많다
SPAWN_NOTE_CHARS = 600
# 워크스페이스를 모르는 spawn 할일의 note 표지. 세션이 분류하면 이 줄을 지우고 그 자리로 옮긴다(spawn_link).
# 이 줄이 있는 할일의 카테고리는 사람이 고른 것이 아니라 자동 분류 학습·세션 카테고리 상속에서 뺀다
SPAWN_PROVISIONAL_LINE = "자리: 임시 카테고리 — 이 세션이 분류되면 그 카테고리로 옮겨진다"
# 임시 자리 할일을 알아보는 머리. 워크스페이스가 있던 때 줄('…분류하면 그 워크스페이스·카테고리로 옮겨진다')도
# 이 머리로 시작한다 — 운영 DB 에 남은 옛 note 도 같은 할일로 본다
SPAWN_PROVISIONAL_MARK = "자리: 임시 카테고리 —"

# 근거 문서 키 추출. Jira 키는 모양만 보면 'UTF-8'·'KT-7' 같은 오탐이 많아 이 회사에서 쓰는
# 프로젝트 접두사만 받는다(11-16 Jira 조회로 확인: PFD 플랫폼개발부문 · YAIW 미디어전략부문 · KT 코리아타임스).
# 브라우즈 URL 로 적힌 키는 접두사와 관계없이 받는다
ATLASSIAN_BASE = "https://hankookilbo.atlassian.net"
JIRA_PROJECTS = ("PFD", "YAIW", "KT")
GITHUB_BASE = "https://github.com"
# 'muni PR #69' 처럼 레포 이름만 적은 PR. 조직이 빠져 있어 여기 있는 레포만 받는다.
# 'HK #35' 같은 축약은 레포를 확정할 수 없어 자동으로 잇지 않는다
KNOWN_REPOS = {
    "hk-herb-server": "hkilbo",
    "kt-cms-server": "hkilbo",
    "muni": "hkilbo",
    "hk-vms-server": "hkilbo",
    "hk-library-server": "hkilbo",
    "hk-herb-engine": "hkilbo",
    "hk-techblog-client": "hkilbo",
    "herb-library-client": "hkilbo",
    "hk-appshell-client": "hkilbo",
    "hk-article-client": "hkilbo",
    "kt-herb-client": "hkilbo",
}

# ── 세션 결과물 ──────────────────────────────────────────────────────────
# 세션이 만들거나 고친 것을 세션 transcript 의 쓰기 호출과 완료 보고(--open)에서 뽑아 결과 관계로 잇는다.
# 읽기만 한 문서는 결과가 아니다 — 아래 도구 이름은 쓰기 호출만 담는다.
# MCP 서버 이름이 연결 방식마다 달라(Atlassian_Rovo·Atlassian_MCP·Atlassian) 도구 이름 끝부분으로 고른다
RESULT_CONFLUENCE_CREATE = ("createConfluencePage", "createConfluenceContent")
RESULT_CONFLUENCE_UPDATE = ("updateConfluencePage", "updateConfluenceContent")
RESULT_JIRA_CREATE = ("createJiraIssue",)
RESULT_JIRA_EDIT = ("editJiraIssue", "transitionJiraIssue")
RESULT_JIRA_COMMENT = ("addCommentToJiraIssue", "addOrEditJiraIssueComment")
# 결과 하나에 붙는 동작 이름. 같은 세션이 같은 문서를 여러 번 고치면 한 관계에 모아 적는다
RESULT_ACTIONS = ("생성", "수정", "댓글", "발행", "보고")
# Write 로 새로 만든 파일 중 결과가 아닌 자리 — 에이전트의 작업 폴더·메모리·설정과 임시 폴더.
# 숨김 폴더(.config·.claude 등)가 낀 경로도 설정이라 뺀다. 레포 안 파일은 커밋·PR 로 보이므로 뺀다
RESULT_FILE_SKIP_DIRS = (os.path.expanduser("~/.claude"), "/tmp")
# 경로 중간에 끼면 결과가 아닌 폴더 이름 — Windows 앱 데이터(도구 설치 스크립트가 여기 생긴다)
RESULT_FILE_SKIP_PARTS = ("AppData", "node_modules", "__pycache__")
# 로컬 미리보기 주소는 배포된 사이트가 아니다 — 서버를 내리면 열리지 않는다
RESULT_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")
# 훅(Stop·SessionEnd) 한 번에 transcript 하나에서 읽을 최대 바이트. 훅 시간 제한(2초) 안에 끝나야 한다 —
# 못 다 읽은 나머지는 다음 턴 훅이 이어 읽는다. 백필은 제한 없이 읽는다
RESULT_HOOK_MAX_BYTES = 4 * 1024 * 1024
# 결과를 아직 못 받은 쓰기 호출이 이만큼 안쪽(파일 끝 기준)에 있으면 그 줄부터 다시 읽도록 오프셋을 멈춘다.
# 더 멀리 있는 것은 중단된 호출로 보고 버린다 — 멈춘 오프셋이 매 턴 같은 구간을 다시 읽게 하면 안 된다
RESULT_PENDING_HOLD_BYTES = 256 * 1024

# ── 미분류 자동 분류 ─────────────────────────────────────────────────────
# 경합 기준 — 1위와 2위 점수 차를 글의 키워드 수로 나눈 값. 11-18 실측(각 항목을 빼고 나머지로 학습해 맞히기,
# 세션 정답은 연결 할일의 현재 카테고리), 근거 4개 이상 기준:
#   0.2 → 세션 81%·할일 90% 맞음(34%·36% 분류) / 0.3 → 90%·94%(24%·27% 분류)
# 틀린 분류는 사람이 다시 찾아 고쳐야 하므로 열에 아홉 맞는 0.3 을 쓴다
CLASSIFY_MIN_MARGIN = 0.3
# 배운 키워드가 이보다 적게 걸리면 근거 부족 — 3개로는 매니저 기상 지시('시작·컨텍스트·않는')가
# 근거 없이 '개발'로 갔다(11-18 dry-run)
CLASSIFY_MIN_EVIDENCE = 4
# 분류된 할일이 이보다 적으면 배울 게 없어 아무것도 자동 분류하지 않는다(처음 쓰는 사람)
CLASSIFY_MIN_TRAINING = 30
CLASSIFY_SMOOTHING = 0.1
# 근거 키워드 선별. 카테고리 크기를 맞춘 출현 비율에서 한 카테고리 몫이 SHARE 이상이고, MIN_DOCS 건 이상의
# 할일에 나온 말만 근거로 쓴다 — 어디에나 나오는 조사·어미 조각과 한 번 나온 우연한 말을 뺀다
CLASSIFY_KEYWORD_SHARE = 0.5
CLASSIFY_KEYWORD_MIN_DOCS = 3
# dry-run·판정 결과에 보여줄 근거 키워드 수
CLASSIFY_EVIDENCE_SHOWN = 5
# 세션 첫 지시·note 에서 판정에 쓸 앞부분. 뒤로 갈수록 세부 절차·예외라 다른 카테고리 말이 섞인다
AUTO_CLASSIFY_BODY_CHARS = 600
