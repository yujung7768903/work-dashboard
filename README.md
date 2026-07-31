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
│       └── usage.py                 # 한도 사용률·토큰 추이
│
├── hooks/
│   └── dash_hook.py                 # Claude Code 훅 단일 진입점
│
├── static/                          # ES 모듈 프론트엔드 (번들러 없음)
│   ├── index.html                   # 단일 페이지
│   ├── css/app.css                  # 전체 스타일
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

주입 블록은 두 갈래다.

| 상황 | 블록 | 내용 |
| --- | --- | --- |
| 브랜치의 Jira ID = 워크스페이스의 `jira_id` | `<work-dashboard state="classified">` | 배경·목적·목표·고려사항 + 할일 목록(컨텍스트 노트 유무 표시) + 범위 준수 지침 |
| 그 외 | `<work-dashboard state="unclassified">` | 현재 위치·브랜치, 카테고리 6개, 진행 중 워크스페이스 목록, 분류 절차 지시 |

두 블록 모두 꼬리에 공통 규칙이 붙는다 — 다른 세션이 같은 코드·문서를 고칠 수 있으니 착수 전에 최신 상태를 다시 읽으라는 것.

분류는 훅이 못 한다(셸은 질문 내용을 이해할 수 없다). 훅이 넘긴 지시를 받아 Claude 가 아래 명령으로 직접 등록하고, 분류 전이면 매 프롬프트마다 지시가 다시 들어간다.

```bash
python3 dash.py sessions                                  # 돌고 있는 세션
python3 dash.py classify <session> --category 개발 --workspace 2
python3 dash.py link-todo <session> 3                     # 세션이 잡은 할일 연결
```

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
| `meta` | 내부 플래그 저장소. 현재는 `categories_seeded` 하나 | `key`(PK), `value` | — |

## 규칙 몇 가지

- 우선순위는 워크스페이스 순위 + 할일 순서로만 표현한다. **할일은 중요도가 아니라 착수 가능한 순서로 놓는다.**
- 카테고리는 그룹핑 분류일 뿐 우선순위 계산에 관여하지 않는다.
- 카테고리 삭제는 비어 있을 때만. 워크스페이스 삭제 시 소속 할일은 미분류로 내려간다. 할일 삭제는 하위할일까지 지운다.
- 웹과 CLI가 같은 DB를 쓴다. CLI 변경을 웹에서 보려면 새로고침한다. 세션 영역만 2초 폴링한다.
- 마크다운은 루트 `.markdownlint.json` 을 따른다. 표 구분행은 `| --- | --- |`, 코드펜스에는 언어를 붙인다(`text`, `bash`, `json` 등).

## 세션 연동 (②)

코드·훅 등록 모두 적용됨 (2026-07-30 확인). 남은 항목은 `docs/superpowers/specs/2026-07-30-session-mapping-spec.md` 에 결정으로 적혀 있다 (세션 인자 env 폴백, fork 세션 분류 상속).

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

경로는 모두 `docs/superpowers/` 기준. ②③④ 문서는 각각 (a) 문제 (b) 확정 결정과 근거 (c) 안 하는 것 (d) 파일 경계를 담고 있어 그대로 착수할 수 있다.

## 아직 없는 것

- 결정 대기 큐 (③), 자율 실행 (④) — 스펙만 있고 코드 없음
- 완료 항목 아카이브, 할일 의존성, 카테고리 우선순위
