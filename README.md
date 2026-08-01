# 작업 대시보드

카테고리 > 워크스페이스 > 할일 > 하위할일 4계층으로 작업을 관리하는 1인용 로컬 도구.
사람은 웹으로, Claude는 CLI로 같은 sqlite DB를 쓴다. 외부 의존성 0.

## 실행

```bash
python3 server.py                    # http://127.0.0.1:9080
python3 server.py --host 0.0.0.0     # 폰에서 볼 때 (인증 없음, LAN 노출 주의)
```

## 테스트

```bash
python3 -m tests
```

## 프로젝트 구조

```text
work-dashboard/
│
├── dash.py                          # CLI 진입점. 파싱·위임·출력만
├── server.py                        # 웹 서버 진입점 (http.server, 프레임워크 없음)
│
├── app/                             # 도메인 계층
│   ├── constants.py                 # 전역 상수. 매직넘버는 전부 여기로
│   ├── db.py                        # 연결·스키마·트랜잭션
│   ├── errors.py                    # 도메인 예외
│   ├── ordering.py                  # 정렬 순서 계산 공용 로직
│   │
│   ├── repositories/                # 엔티티별 저장·조회와 정합성 규칙
│   │   ├── categories.py            # 카테고리
│   │   ├── workspaces.py            # 워크스페이스
│   │   ├── todos.py                 # 할일
│   │   ├── subtasks.py              # 하위할일
│   │   └── sessions.py              # 세션 등록·분류·상태·할일 연결·정리
│   │
│   └── services/                    # 여러 엔티티에 걸치는 로직
│       ├── board.py                 # 보드 트리 조립
│       ├── planning.py              # 다음에 할 일 선정
│       ├── session_link.py          # 세션 주입 블록 조립
│       ├── transcript.py            # Claude Code jsonl 읽기 (앞·꼬리 조각)
│       ├── history.py               # 초기 설정용 히스토리 스캔·요약
│       └── usage.py                 # 한도 사용률·토큰 추이
│
├── hooks/
│   ├── dash_hook.py                 # Claude Code 훅 단일 진입점
│   ├── worktree_serve.py            # Stop: 고친 워크트리에 서버가 없으면 띄우라고 지시
│   └── worktree_guard.py            # PreToolUse: 메인 체크아웃 소스 편집 차단 (미등록)
│
├── static/                          # ES 모듈 프론트엔드 (번들러 없음)
│   ├── index.html                   # 단일 페이지
│   ├── css/
│   │   ├── app.css                  # 디자인 토큰 정의 + 공통·보드 스타일
│   │   └── usage.css                # 사용량 화면 전용 (토큰은 app.css 것을 참조)
│   └── js/
│       ├── main.js                  # 부트스트랩·탭 전환
│       ├── api.js                   # fetch 래퍼
│       ├── board.js                 # 보드 렌더
│       ├── categories.js            # 카테고리 관리
│       ├── workspace.js             # 워크스페이스 상세
│       ├── sessions.js              # 활성 세션 (2초 폴링)
│       ├── usage.js                 # 사용량 화면
│       ├── chart.js                 # 차트 렌더
│       └── dnd.js                   # 드래그 재정렬
│
├── tests/                           # python3 -m tests 로 일괄 실행
│   ├── __main__.py                  # 러너
│   ├── support.py                   # 임시 DB 픽스처
│   └── test_*.py                    # 계층별 테스트
│
└── docs/superpowers/                # 설계·계획 문서
    ├── specs/                       # 단계별 설계와 확정 결정
    └── plans/                       # 구현 계획
```

## 훅 동작

`hooks/dash_hook.py <이벤트>` 하나가 네 이벤트를 분기한다. `~/.claude/settings.json` 에 절대 경로로 등록돼 있고 타임아웃은 2초. **어떤 실패에서도 `exit 0` 무출력으로 끝난다** — 대시보드 문제로 Claude 세션이 안 열리는 것이 최악의 실패이기 때문이다.

| 시점 | 이벤트 | 하는 일 | 세션에 주입되는 것 |
| --- | --- | --- | --- |
| 세션이 열릴 때 | `SessionStart` | stdin JSON 의 `session_id`·`cwd` 로 세션 등록, `cwd` 에서 `git branch --show-current` 조회, 브랜치의 Jira ID 로 워크스페이스 자동 매칭 | 워크스페이스 블록 또는 분류 지시 블록 |
| 지시를 넣을 때마다 | `UserPromptSubmit` | 상태를 `working` 으로, 마지막 지시를 120자로 잘라 저장 | 분류 전이면 분류 지시 재주입, 분류됐으면 무출력 |
| 응답이 끝날 때 | `Stop` | 상태를 `idle` 로 | 없음 |
| 세션이 닫힐 때 | `SessionEnd` | 상태를 `ended` 로, 종료 시각 기록 | 없음 |

### 워크트리 서버 훅 (`hooks/worktree_serve.py`)

워크트리에서 코드를 고쳐 놓고 확인할 화면을 안 띄우면, 사용자는 결과를 눈으로 볼 수 없다. 이 `Stop` 훅이 그걸 막는다.

- **등록 위치가 다르다.** `~/.claude/settings.json`(그 PC 전용, 절대 경로)이 아니라 저장소에 커밋되는 `.claude/settings.json` 에 `$CLAUDE_PROJECT_DIR` 기준으로 등록된다. 그래서 clone 한 다른 PC에서도 따로 설정할 것이 없다.
- **거는 조건**: 이번 세션에 `.claude/worktrees/<이름>/` 안의 파일을 고쳤고, 그 워크트리에 `server.py`·`manage.py`·`package.json` 중 하나가 있고(= 띄울 수 있는 프로젝트), cwd 가 그 워크트리인 서버 프로세스가 없을 때.
- **이미 떠 있으면 관여하지 않는다.** 다른 세션이 그 화면을 보고 있을 수 있어 재기동하지 않는다.
- 막으면서 빈 포트(9080–9139)를 골라 주고, 응답을 `- 워크트리:` / `- url:` / `- 작업 요약:` 세 줄로 끝내라고 지시한다.
- 프로세스 조회는 `ps` + (`/proc` 또는 `lsof`) 라서 리눅스·macOS 양쪽에서 같게 동작한다. `stop_hook_active` 면 통과해 무한 루프를 막고, 어떤 실패에서도 `exit 0` 으로 fail-open 한다.

주입 블록은 세 갈래다.

| 상황 | 블록 | 내용 |
| --- | --- | --- |
| 브랜치의 Jira ID = 워크스페이스의 `jira_id` | `<work-dashboard state="classified">` | 배경·목적·목표·고려사항 + 할일 목록(컨텍스트 노트 유무 표시) + 범위 준수 지침 |
| 워크스페이스가 0개이고 사용자가 거절한 적 없음 | `<work-dashboard state="onboarding">` | 초기 설정 절차 7단계 (아래 참고) |
| 그 외 | `<work-dashboard state="unclassified">` | 현재 위치·브랜치, 카테고리 6개, 진행 중 워크스페이스 목록, 분류 절차 지시 |

세 블록 모두 꼬리에 공통 규칙이 붙는다 — 다른 세션이 같은 코드·문서를 고칠 수 있으니 착수 전에 최신 상태를 다시 읽으라는 것.

분류는 훅이 못 한다(셸은 질문 내용을 이해할 수 없다). 훅이 넘긴 지시를 받아 Claude 가 아래 명령으로 직접 등록하고, 분류 전이면 매 프롬프트마다 지시가 다시 들어간다.

```bash
python3 dash.py sessions                                  # 돌고 있는 세션
python3 dash.py classify <session> --category 개발 --workspace 2
python3 dash.py link-todo <session> 3                     # 세션이 잡은 할일 연결
```

### 초기 설정 (⑤)

워크스페이스가 하나도 없는 상태에서 세션을 열면 분류 대신 **초기 설정 블록**이 주입된다. Claude 가 사용자에게 최근 며칠 치 히스토리를 볼지(7일 / 14일 / 안 함) 묻고, 스캔 결과로 카테고리·워크스페이스를 제안한 뒤 확인받아 등록한다.

```bash
python3 dash.py scan-history --days 7     # 세션당 한 줄 요약 (Claude 가 읽는 입력)
python3 dash.py onboard                   # 초기 설정이 필요한 상태인지
python3 dash.py onboard --skip            # 자동 분류 거절. 이후 다시 묻지 않음
```

`scan-history` 는 `~/.claude/projects/*/*.jsonl` **전체**에서 mtime 이 기간 안인 파일만 골라 **앞 64KB** 만 읽고, 프로젝트 위치별로 묶어 세션당 한 줄(시작~최근 날짜 + 첫 지시 200자)로 뱉는다. 전문은 수백 MB 라 세션에 넣을 수 없기 때문이다. 슬래시 명령·자동 압축 요청은 첫 지시에서 걸러낸다.

**묶는 것과 하한선 적용은 코드가 아니라 Claude 가 한다** — 의미 판단이라 셸이 못 한다. 세션 `ONBOARDING_MIN_SESSIONS`건 미만인 묶음은 워크스페이스로 만들지 않고 "기타" 한 줄로만 표시한다. 확인 트리가 검수 가능한 크기를 넘으면 사용자가 읽지 않고 승인하게 되기 때문이다.

묶는 단위는 **작업 위치(디렉토리) 하나 = 워크스페이스 하나**다. 한 저장소 안의 기획·구현·배포는 워크스페이스가 아니라 **착수 순서대로 놓는 할일**이다 — 워크스페이스로 쪼개면 `classified` 블록이 주입할 배경·목적이 세션마다 갈린다. 홈·scratch 성격의 위치만 내용으로 다시 쪼갠다.

워크스페이스마다 **할일도 함께 만들고 상태까지 추정해 넣는다.** 보드가 할일 0개인 워크스페이스를 통째로 감추기 때문이다(`board.py` 의 `if not todos: continue`) — 워크스페이스만 만들면 화면에 아무것도 안 나타나 초기 설정이 실패한 것처럼 보인다. 추정이 틀려도 보드에서 바로 고칠 수 있다.

워크스페이스 필드를 채울 때의 기준은 **"매 세션 주입돼도 값어치가 있는가"** 하나다.

| 필드 | 넣는 것 | 안 넣는 것 |
| --- | --- | --- |
| 배경 | 왜 이 일이 존재하는가. 도메인의 문제 | 기술 스택, URL, 포트, 저장소 주소 |
| 목적 | 그 문제를 어떤 방향으로 푸는가 | 완료 조건 |
| 목표 | 끝났다고 판정할 수 있는 상태 | 방향·이유 |
| 고려사항 | 벗어나면 안 되는 제약·금지 | 구현 디테일, 일시적 이슈 |
| 할일 `note` | 그 할일 착수할 때만 필요한 구체 정보 | 워크스페이스 전체에 걸린 것 |

완료 플래그는 두지 않는다 — 워크스페이스가 하나라도 생기면 트리거 조건이 저절로 깨진다. 거절만 `meta.onboarding_declined` 에 남는다. 따라서 **워크스페이스를 전부 지우면 초기 설정이 다시 뜬다**(의도된 동작).

`link-todo` 는 `session_todos` 에 연결만 하고 할일 상태는 바꾸지 않는다 — 착수 시 `doing` 전환은 아직 없다(할일 32).

세션 정리는 별도 크론 없이 조회할 때 함께 수행한다 — `last_seen_at` 이 24시간 지난 `idle` 은 `ended` 로 간주하고, `ended` 이면서 연결된 할일이 없는 세션은 7일 뒤 삭제한다.

## 데이터베이스

- **DB**: sqlite3 (파이썬 표준 라이브러리 `sqlite3`, 외부 드라이버 없음)
- **위치**: `~/.claude/work-dashboard/dash.db`. 환경변수 `WORK_DASHBOARD_DB` 로 덮어쓸 수 있고, `connect(path)` 인자가 있으면 그게 최우선
- **접근 주체**: 웹 서버·CLI·훅이 같은 파일을 직접 연다. 서버 프로세스가 중재하지 않음

`app/db.py` 의 `connect()` 가 최초 호출될 때 하는 일 (매 연결마다 실행되지만 전부 멱등):

- DB 파일의 부모 디렉터리를 `makedirs(exist_ok=True)` 로 생성
- `PRAGMA foreign_keys=ON` — 참조 무결성 강제
- `PRAGMA journal_mode=WAL` — 웹·CLI·훅 동시 접근 대비
- `PRAGMA busy_timeout=5000` — 잠금 대기 5초
- `CREATE TABLE IF NOT EXISTS` 로 테이블 7개 생성
- 카테고리 6개(개발 / 운영 / 장애 대응 / 개발환경 개선 / 스킬 개발 / 프로세스 개선) 시드. `meta` 의 `categories_seeded` 플래그로 **최초 1회만** — 사용자가 지운 카테고리가 되살아나면 안 되기 때문

시각 컬럼(`*_at`)은 전부 TEXT 이며 ISO8601 UTC 초 단위(`2026-07-31T04:12:33+00:00`).

### 테이블 구조

| 테이블 | 역할 | 주요 컬럼 | 참조 |
| --- | --- | --- | --- |
| `categories` | 최상위 그룹핑. 우선순위 계산에는 관여 안 함 | `id`, `name`(UNIQUE), `sort_order`, `created_at` | — |
| `workspaces` | 브랜치·Jira 단위 큰 작업. 배경·목적·목표·고려사항 보관 | `id`, `name`, `background`, `purpose`, `goal`, `considerations`, `status`(active/paused/done), `sort_order`, `jira_id`, `created_at`, `updated_at` | `category_id` → `categories` |
| `todos` | 할일. 워크스페이스 없이 카테고리 직속도 가능 | `id`, `title`, `note`(컨텍스트 노트), `status`(todo/doing/done), `sort_order`, `completed_at`, `created_at`, `updated_at` | `category_id` → `categories`, `workspace_id` → `workspaces` (nullable) |
| `subtasks` | 하위할일. 할일 삭제 시 함께 삭제 | `id`, `title`, `status`(todo/doing/done), `sort_order`, `created_at` | `todo_id` → `todos` |
| `sessions` | Claude Code 세션. 훅이 등록·갱신 | `id`, `claude_session_id`(UNIQUE), `cwd`, `git_branch`, `state`(working/idle/ended), `last_prompt`(120자), `started_at`, `last_seen_at`, `ended_at` | `category_id` → `categories`, `workspace_id` → `workspaces` (둘 다 nullable = 미분류) |
| `session_todos` | 세션 ↔ 할일 N:N 연결 | `created_at`, PK = (`session_id`, `todo_id`) | `session_id` → `sessions`, `todo_id` → `todos` |
| `meta` | 내부 플래그 저장소. `categories_seeded`, `onboarding_declined` | `key`(PK), `value` | — |

## 규칙 몇 가지

- 우선순위는 워크스페이스 순위 + 할일 순서로만 표현한다. **할일은 중요도가 아니라 착수 가능한 순서로 놓는다.**
- 카테고리는 그룹핑 분류일 뿐 우선순위 계산에 관여하지 않는다.
- 카테고리 삭제는 비어 있을 때만. 워크스페이스 삭제 시 소속 할일은 미분류로 내려간다. 할일 삭제는 하위할일까지 지운다.
- 웹과 CLI가 같은 DB를 쓴다. CLI 변경을 웹에서 보려면 새로고침한다. 세션 영역만 2초 폴링한다.
- 마크다운은 루트 `.markdownlint.json` 을 따른다. 표 구분행은 `| --- | --- |`, 코드펜스에는 언어를 붙인다(`text`, `bash`, `json` 등).

## 디자인 토큰

`static/css/app.css` 의 `:root` 가 유일한 출처다. `usage.css` 는 정의하지 않고 참조만 한다.
**font-size·padding·margin·gap·border-radius 에 생 px 을 쓰지 않는다** — `tests/test_css_tokens.py` 가 어기면 실패시킨다. width·height·box-shadow 같은 그래픽 치수(점·바 두께)는 격자와 무관하므로 예외.

| 종류 | 토큰 | 값 | 쓰는 곳 |
| --- | --- | --- | --- |
| 간격 | `--sp-2` ~ `--sp-48` | 2 / 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 | 4px 격자. `--sp-2` 만 반 칸. 6·9·10·11·14 같은 사이값은 쓰지 않는다 |
| 간격 별칭 | `--gap`, `--pad-card` | 둘 다 16px | 카드 사이 간격 / 카드 내부 여백. 카드 안 헤더·행은 `--sp-12` |
| 글자 | `--fs-display` | 32px | 카드 하나를 대표하는 큰 수치 |
| | `--fs-title` | 20px | 화면 제목 |
| | `--fs-body` | 13px | 본문. 카드 제목은 같은 크기에 700 |
| | `--fs-sm` | 11px | 보조 본문·라벨·메타·캡션·표·컨트롤 |
| | `--fs-micro` | 9px | 배지·칩·차트 눈금 |
| 행간 | `--lh-tight` / `--lh-heading` / `--lh-body` | 1.1 / 1.3 / 1.55 | 큰 수치 / 제목·배지 / 본문 |
| 둥글기 | `--r-card` / `--r-ctl` / `--r-pill` | 12 / 8 / 999px | 카드 / 컨트롤·중첩 카드 / 알약·점 |
| 그 외 | `--icon-box` | 24px | 16px 아이콘을 담는 정사각 면 |

새 요소를 만들 때의 판단 기준:

- 보조 글자를 나눈 기준 — 글로 읽는 것(캡션·메타·표)은 `--fs-sm`, 배지·칩·눈금은 `--fs-micro`
- 굵기는 400(본문)·500(라벨·보조)·600(강조·세션 이름)·700(카드 제목·큰 수치) 네 단만
- 라벨은 어디서든 `--fs-sm` + 500 + `--muted`, 카드 제목은 `--fs-body` + 700
- 초점 링은 app.css 의 전역 `:focus-visible` 하나가 그린다. 요소마다 따로 정의하지 않는다 (입력 필드만 `:focus` 링을 따로 갖는다)
- 아이콘↔글자 간격은 `--sp-8`, 칩·배지 내부는 `--sp-4`
- 차트 글자만 예외로 `static/js/chart.js` 의 `AXIS_FONT`(11 = `--fs-micro`), `DONUT_TOTAL_FONT`(20 = `--fs-title`) 가 정한다. SVG 좌표 계산에 쓰이기 때문

## 세션 연동 (②)

코드·훅 등록 모두 적용됨 (2026-07-30 확인). 남은 항목은 `docs/superpowers/specs/2026-07-30-session-mapping-spec.md` 에 결정으로 적혀 있다 (세션 인자 env 폴백, fork 세션 분류 상속).

보드의 세션 줄과 할일 줄은 **같은 팝업**을 연다. 팝업은 탭 두 개다.

| 탭 | 내용 | 기본 활성 |
|---|---|---|
| 개요 | 할일 제목, 생성·수정·완료 시각(최근 순), note 전문 | 할일에서 열 때 |
| 세션 | 세션 id·위치·최근 대화 10건, 워크스페이스·카테고리 지정 | 세션에서 열 때 |

세션에서 열면 개요 탭에 그 세션이 `link-todo` 로 잡은 할일이 뜨고, 할일에서 열면 세션 탭에 그 할일을 마지막으로 잡은 세션이 뜬다. note 는 세션에 `(컨텍스트 #id)` 표시만 주입되므로 전문을 보는 자리는 이 팝업이다. 최근 대화는 `~/.claude/projects/*/<세션id>.jsonl` 꼬리에서 읽는다.

### 다른 PC 에 옮길 때

`hooks/dash_hook.py` 의 **절대 경로**가 필요하다. 워크트리에서 쓰고 있다면 워크트리가 지워질 때 훅이 깨지므로 영구 경로에 둔 뒤 등록한다.

`~/.claude/settings.json` 백업 후 네 이벤트에 각각 추가한다(마지막 인자만 이벤트명으로 바꿈).

```json
{"hooks": [{"type": "command", "command": "python3 <절대경로>/hooks/dash_hook.py SessionStart", "timeout": 2}]}
```

같은 작업에서 `hooks.SessionStart` 의 `bash ~/.claude/skills/scope-guard/session-inject.sh` 항목을 **제거**한다. 남겨두면 같은 내용이 두 번 주입된다.

### scope-guard 흡수 (적용 완료)

`~/.claude/skills/scope-guard/scope_db.py` 가 `app/services/session_link.py` 의 `scope_guard_block()` 을 쓰는 dash.db 어댑터로 교체돼 있고(`scope_db.py.bak` 보존), `session-inject.sh` 훅은 `settings.json` 에서 제거됐다. 목표·하위단계는 대시보드의 워크스페이스·할일이다. 흡수 범위를 여기서 끝내는 근거는 ② 스펙 D4 참고.

**주의** — `scope_db.py set-steps` 는 워크스페이스의 할일을 전부 지우고 다시 넣는다. 할일에 하위할일·컨텍스트 노트가 붙은 워크스페이스에서는 실행하지 말 것.

### 롤백

훅 등록 후 문제가 생기면:

```bash
cp ~/.claude/settings.json.bak ~/.claude/settings.json
cp ~/.claude/skills/scope-guard/scope_db.py.bak ~/.claude/skills/scope-guard/scope_db.py
cp ~/.claude/scope-guard/scope.db.bak ~/.claude/scope-guard/scope.db
```

## 설계 문서

| 단계 | 문서 | 상태 |
| --- | --- | --- |
| ① 4계층 + 웹/CLI | `specs/2026-07-29-work-dashboard-design.md`, `plans/2026-07-29-work-dashboard.md` | 구현 완료 |
| ② 세션 매핑 | `specs/2026-07-29-session-link-design.md` (설계) + `specs/2026-07-30-session-mapping-spec.md` (확정 결정) | 대부분 구현, 잔여 2건 |
| ③ 결정 대기 큐 | `specs/2026-07-30-decision-queue-spec.md` | 결정 확정, 미구현 |
| ④ 자율 실행 | `specs/2026-07-30-autorun-spec.md` | 결정 확정, 미구현 |
| ⑤ 초기 설정(온보딩) | `specs/2026-08-01-onboarding-spec.md` | 구현 완료 |

경로는 모두 `docs/superpowers/` 기준. ②③④ 문서는 각각 (a) 문제 (b) 확정 결정과 근거 (c) 안 하는 것 (d) 파일 경계를 담고 있어 그대로 착수할 수 있다.

## 아직 없는 것

- 결정 대기 큐 (③), 자율 실행 (④) — 스펙만 있고 코드 없음
- 완료 항목 아카이브, 할일 의존성, 카테고리 우선순위
