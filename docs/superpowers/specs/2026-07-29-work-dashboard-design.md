# 작업 대시보드 설계

작성일: 2026-07-29 · 상태: 설계 확정 (미구현)

## 배경

업무가 세 갈래로 흩어져 있다. 계획된 메인 작업(KT 동시성 이슈 해결, 헤르메스 테스트), 꾸준히 하는 효율화 작업(터미널 세팅, 스킬 개발, 단축키), 그리고 계획 불가능한 유입(문의, 장애 대응). Jira에 남는 건 일부뿐이라 "지금 내가 뭘 하고 있는지"가 한 화면에 없다.

여기에 두 가지 문제가 겹친다. 하나는 스코프 크립 — 작업 범위가 자꾸 넓어진다. 이를 막으려고 `scope-guard` 스킬을 만들어 Jira 단위 배경·목표·하위단계를 sqlite에 저장하고 세션 시작 시 주입하고 있으나, Jira ID가 PK라서 Jira 없는 작업을 담지 못하고 depth도 1단계뿐이다. 다른 하나는 Claude 세션마다 같은 맥락을 반복 설명해야 한다는 것.

## 목적

작업을 계층으로 관리하는 단일 저장소를 만들고, 그 저장소를 사람(웹)과 Claude(CLI)가 함께 쓴다. 이 저장소가 나중에 세션 주입(②)과 자율 실행(④)의 기반이 된다. scope-guard도 결국 이 저장소를 보게 되지만 그 전환은 ②에서 한다.

## 목표 (1차 범위)

- 카테고리 > 워크스페이스 > 할일 > 하위할일 4계층의 생성·수정·삭제·이동·재정렬
- 워크스페이스 기준 / 카테고리 기준 두 가지 그룹핑 조회
- 워크스페이스마다 배경·목적·목표·추가 고려사항 보관
- 우선순위를 순위(sort_order)로 표현하고 "다음에 할 일"을 한 줄로 도출
- Claude가 CLI로 같은 DB에 접근
- 오늘 완료한 할일을 daily-todo(Confluence 주간보고)로 넘기는 경로 제공

## 범위에서 뺀 것 (후속 스펙)

이 문서는 ①만 다룬다. 나머지는 각각 별도 스펙으로 진행한다.

| 후속 | 내용 | 이번 설계가 준비해 둔 것 |
|------|------|--------------------------|
| ② 세션 매핑 | 할일/하위할일을 Claude 세션에 연결하고 워크스페이스 배경·목적을 자동 주입. **scope-guard 흡수도 여기서** | `sessions` 테이블을 **추가**만 하면 되도록 기존 4테이블을 고정. `workspaces.jira_id`가 scope-guard 연결점. 세션 식별 방식은 ②에서 결정 |
| ③ 결정 대기 큐 | Claude가 판단을 요청하고 사용자가 목록에서 즉시 결정 | 없음 (테이블 신규 추가 예정) |
| ④ 자율 실행 | 스스로 다음 일을 찾아 수행, 세션 리밋 시 대기 후 재개 | `dash.py next` 가 진입점 |

②의 세션 식별에는 주의가 필요하다. tmux `capture-pane` 기반 감지(pixel-office 방식)는 WSL에서 claude를 직접 띄우거나 agents 창을 쓰는 경우가 많아 재사용할 수 없다.

## 용어

- **카테고리** — 업무 성격 분류. 운영, 장애 대응, 개발환경 개선, 스킬 개발, 프로세스 개선, 개발 등. 사용자가 자유롭게 추가·수정·삭제한다.
- **워크스페이스** — 하나의 큰 작업 단위. 배경·목적·목표·추가 고려사항을 가진다. 할일을 묶는 그룹 성격.
- **할일 / 하위할일** — 실제 수행 단위. 할일은 워크스페이스 없이 카테고리에 바로 붙을 수 있다(미분류).

## 아키텍처

진입점 두 개(CLI·HTTP)가 같은 도메인 계층을 호출하는 3계층 구조다.

```
~/work-dashboard/
  dash.py                    CLI 진입점. 인자 파싱 → 도메인 호출 → 출력
  server.py                  HTTP 진입점. 라우팅 → 도메인 호출 → JSON 직렬화
  app/
    db.py                    연결, WAL·busy_timeout, 스키마 초기화, 트랜잭션 헬퍼
    errors.py                NotFound / Conflict / Validation 도메인 예외
    ordering.py              sort_order 재부여 공통 로직
    repositories/
      categories.py  workspaces.py  todos.py  subtasks.py
    services/
      board.py               그룹핑 트리 조립 (워크스페이스 기준 / 카테고리 기준)
      planning.py            next, done-today
  static/
    index.html               마크업만
    css/app.css
    js/  api.js  board.js  workspace.js  categories.js  dnd.js  main.js
  tests/                     계층별 테스트
  docs/superpowers/specs/2026-07-29-work-dashboard-design.md
~/.claude/work-dashboard/dash.db   # DB. 코드와 분리 (scope-guard 전례)
```

### 계층 규칙

- **진입점(`dash.py`, `server.py`)은 도메인 로직을 갖지 않는다.** 파싱·위임·출력만 한다. 웹과 CLI가 같은 repository·service를 호출하므로 로직이 두 벌 생기지 않는다.
- **repository는 한 엔티티의 저장·조회만 담당한다.** 여러 엔티티에 걸치는 조립은 service로 올린다.
- **service는 실제 로직이 있는 곳에만 둔다.** 보드 트리 조립과 계획(next·done-today)이 그것이다. 단순 CRUD는 진입점이 repository를 직접 부른다 — repository를 그대로 통과시키는 빈 service 계층은 만들지 않는다.
- **예외는 `errors.py`의 도메인 타입으로 던진다.** HTTP 계층이 메시지 문자열을 뒤지지 않고 예외 타입만 보고 상태 코드를 정한다. `NotFound` → 404, `Conflict` → 409, `Validation` → 400.
- **엔티티 간 정합성은 repository에서 지킨다.** 할일의 워크스페이스 배정 시 카테고리 동기화, 워크스페이스 삭제 시 할일 강등 같은 규칙은 진입점이 아니라 repository 안에 있어야 어느 경로로 들어와도 동일하게 적용된다.

### 프론트엔드

번들러·프레임워크 없이 ES 모듈로 나눈다. HTTP로 서빙하므로 `<script type="module">`이 그대로 동작한다. `api.js`가 fetch 래퍼를 전담하고 나머지 모듈은 DOM만 다룬다.

실행: `python3 server.py [--host HOST] [--port PORT]`. 기본 `127.0.0.1:9080` (8080·8081 은 흔히 쓰여 충돌 가능). 인증이 없으므로 LAN 노출은 `--host 0.0.0.0` 명시가 필요하다.

## 데이터 모델

```sql
categories(
  id INTEGER PK, name TEXT UNIQUE NOT NULL,
  sort_order INTEGER NOT NULL, created_at TEXT NOT NULL)

workspaces(
  id INTEGER PK, category_id INTEGER NOT NULL REFERENCES categories(id),
  name TEXT NOT NULL,
  background TEXT, purpose TEXT, goal TEXT, considerations TEXT,
  status TEXT NOT NULL DEFAULT 'active',   -- active | paused | done
  sort_order INTEGER NOT NULL,             -- 전역 우선순위. 1등이 최우선
  jira_id TEXT,                            -- 있으면 scope-guard 연결점
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL)

todos(
  id INTEGER PK,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  workspace_id INTEGER REFERENCES workspaces(id),   -- NULL이면 미분류
  title TEXT NOT NULL, note TEXT,
  status TEXT NOT NULL DEFAULT 'todo',     -- todo | doing | done
  sort_order INTEGER NOT NULL,
  completed_at TEXT,                       -- done 전환 시각. daily-todo 집계용
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL)

subtasks(
  id INTEGER PK, todo_id INTEGER NOT NULL REFERENCES todos(id),
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'todo',
  sort_order INTEGER NOT NULL, created_at TEXT NOT NULL)
```

날짜는 ISO8601 UTC (`scope_db.py`와 동일).

### 설계 판단

**할일은 카테고리 필수, 워크스페이스 선택.** `workspace_id`가 NULL이면 미분류 할일이다. 장애나 문의가 들어왔을 때 워크스페이스를 만들거나 배경·목적을 채우도록 강요하지 않기 위한 구조다. 워크스페이스에 배정되면 그 워크스페이스의 카테고리로 `category_id`를 자동 동기화한다. 비정규화지만 이게 있어야 미분류 할일도 카테고리 기준 그룹핑에 나타난다.

**우선순위는 `sort_order` 하나로만 표현한다.** 워크스페이스의 sort_order가 전역 순위이고, 할일의 sort_order는 그룹 내 순서다. 등급(P0~P3)이나 마감일 기반 정렬은 두지 않는다 — 등급은 같은 등급이 쌓이면 다시 모호해지고, 마감일 기반은 마감 없는 효율화 작업을 영원히 뒤로 민다. 재정렬 시 해당 범위를 1..N으로 통째 재부여한다. 항목이 수십 개 규모라 fractional index는 불필요하다.

**"다음에 할 일" 규칙은 한 줄이다.** `status='active'` 워크스페이스를 sort_order 순으로 훑어 첫 미완료(`status != 'done'`) 할일을 고른다. 같은 워크스페이스 안에서는 `doing`이 `todo`보다 먼저다 — 벌여둔 걸 먼저 끝낸다. active 워크스페이스를 다 훑어도 없으면 미분류 할일을 sort_order 순으로 본다. `paused`·`done` 워크스페이스는 후보에서 빠진다. 규칙이 짧아서 ④ 자율 실행이 그대로 물고 들어갈 수 있다.

**순위는 실행 가능한 순서로 매긴다 (규약).** 할일을 나열할 때 중요도 순이 아니라 지금 착수 가능한 순서로 놓는다. 선행 할일이 위, 후행이 아래다. 이 규약이 지켜지면 `sort_order`가 곧 실행 순서라서 `blocked_by` 같은 의존성 필드 없이 ④ 자율 실행이 성립한다. 다만 규약에는 강제력이 없어 순서를 잘못 매기면 ④가 아직 못 하는 일을 집는다. 그때 가서 의존성 필드가 필요해질 수 있고, 이 규약은 그 판단을 ④로 미루기 위한 것이지 문제를 없애는 게 아니다.

**카테고리는 우선순위 계산에 관여하지 않는다.** 그룹핑 분류일 뿐이며 `sort_order`는 표시 순서에만 쓴다. 워크스페이스 순위는 카테고리를 가로지르는 전역 순위다. "특정 카테고리가 항상 우선"이라는 규칙은 실제로 성립하지 않아서(장애가 늘 급한 것은 아니다) 넣지 않는다. 필요해지면 그때 추가한다.

**삭제 정책은 계층마다 다르다.**
- 카테고리: 비어 있을 때만 삭제. 안에 워크스페이스나 할일이 있으면 거부하고 이동을 안내한다. cascade는 실수 한 번으로 큰 작업이 통째로 날아간다.
- 워크스페이스: 삭제 가능. 소속 할일은 `workspace_id=NULL`로 내려가 미분류에 남는다. 데이터 손실 없음.
- 할일: 삭제 시 하위할일 cascade. 하위할일은 할일에 종속되어 독립 존재 의미가 없다.

## 화면

단일 페이지에 탭 세 개.

### ① 보드 (기본)

```
┌──────────────────────────────────────────────────────────┐
│ 다음에 할 일 ▸ KT 동시성 이슈 해결 / 락 재설계 초안 잡기    │
├──────────────────────────────────────────────────────────┤
│ [빠른 추가: ______________________ ] [카테고리 ▾] [+]     │
│ (전체) 💻개발  🛠️운영  🚨장애 대응  ⚙️개발환경 개선  …      │
│ □ 완료 항목 표시                                          │
├──────────────────────────────────────────────────────────┤
│ ▼ 💻 KT 동시성 이슈 해결          (개발)         3/7      │← 상단 배경 = 개발 색
│      ⠿ 락 재설계 초안 잡기                       [doing]  │
│      ⠿ 엑셀 동시 저장 재현 테스트                 [todo]  │
│          └ 하위: k6 시나리오 작성                         │
│ ▼ ⚙️ 작업 대시보드                (개발환경 개선)  0/5     │← 상단 배경 = 개발환경 색
│ ▼ 미분류                                         0/2      │← 상단 배경 = 옅은 회색
│      ⠿ 이미지 입수 문의 회신                      [todo]  │
├──────────────────────────────────────────────────────────┤
│ ▼ 완료                                                    │
│   ▼ 🧩 스킬 저장소 동기화        (스킬 개발)      3/3      │← 카드째 내려온 것
└──────────────────────────────────────────────────────────┘
```

세로 아코디언. 가로 칸반은 워크스페이스가 늘면 가로 스크롤이 감당이 안 되고 폰에서 못 본다.

- 그룹 헤더 드래그 → 워크스페이스 순위 변경 (= 우선순위 변경)
- 할일을 다른 그룹으로 드래그 → 워크스페이스 이동 (`category_id` 자동 동기화)
- 미분류 그룹은 항상 맨 아래 고정. 드래그로 위로 올릴 수 없다
- 할일을 클릭하면 인라인으로 펼쳐져 하위할일 표시·추가·체크
- 할일이 하나도 없는 그룹은 숨긴다. 단 미분류는 비어 있어도 표시한다. 숨겨진 워크스페이스는 상세·카테고리 탭에서 접근 가능하므로 사라지는 것이 아니다
- 완료 항목은 기본 숨김, 토글로 표시

상단 빠른 추가는 장애·문의용이다. 제목을 치고 카테고리만 고르면 미분류 할일로 즉시 들어간다.

**보드는 항상 워크스페이스 기준으로만 그린다.** 그룹핑 전환(워크스페이스/카테고리) 대신 상단에 카테고리 라벨을 두고, 누르면 그 카테고리 워크스페이스만 남긴다. 기본은 `전체`. 필터를 걸면 카테고리가 없는 미분류는 숨는다. 카테고리 기준 그룹핑은 CLI(`ls --group-by category`)와 `/api/tree?group_by=category` 에만 남는다.

**카드 상단 배경은 그 워크스페이스의 카테고리 색이다.** 색은 카테고리 생성 순번으로 팔레트에서 자동 배정되고 카테고리 탭에서 바꿀 수 있다(이모지도 같이). 미분류는 팔레트 밖의 옅은 회색. 카테고리 색을 카드 배경에 `color-mix` 로 옅게 섞어 쓰므로 다크모드가 자동으로 따라온다.

**보드 하단 "완료" 섹션에는 하위 할일이 전부 완료된 워크스페이스가 카드째 내려온다.** 접힌 상태가 기본이고, 그 안에서는 `완료 항목 표시` 와 무관하게 끝낸 할일을 보여준다. 주간보고용 오늘 완료 목록은 CLI `done-today` 로 본다.

### ② 워크스페이스 상세

배경·목적·목표·추가 고려사항 네 칸을 인라인 편집(포커스 아웃 시 저장). 그 아래에 소속 할일과 하위할일. Jira ID와 상태(active/paused/done)도 여기서 설정한다.

### ③ 카테고리 관리

카테고리 추가·이름수정·삭제·순서변경. 각 카테고리 줄에서 "워크스페이스 추가" 버튼으로 바로 생성한다.

## HTTP API

전부 JSON. 응답 본문은 성공 시 리소스, 실패 시 `{"error": "..."}`.

```
GET    /api/tree?group_by=workspace|category    보드 데이터 한 방에
GET    /api/next                                다음에 할 일 1건
GET    /api/done-today?date=YYYY-MM-DD          그날 완료한 할일 (조회 전용)
GET    /api/categories
POST   /api/categories                {name}
PATCH  /api/categories/<id>           {name?}
DELETE /api/categories/<id>                     비어 있지 않으면 409
GET    /api/workspaces/<id>
POST   /api/workspaces                {category_id, name, ...}
PATCH  /api/workspaces/<id>           {name?, background?, purpose?, goal?,
                                       considerations?, status?, jira_id?, category_id?}
DELETE /api/workspaces/<id>                     소속 할일은 미분류로 강등
POST   /api/todos                     {category_id, title, workspace_id?}
PATCH  /api/todos/<id>                {title?, note?, status?, workspace_id?}
DELETE /api/todos/<id>                          하위할일 cascade
POST   /api/subtasks                  {todo_id, title}
PATCH  /api/subtasks/<id>             {title?, status?}
DELETE /api/subtasks/<id>
POST   /api/reorder                   {kind, scope_id?, ids: [...]}
```

`reorder`의 `kind`는 `categories | workspaces | todos | subtasks`. `scope_id`는 todos면 워크스페이스 id(미분류는 null), subtasks면 할일 id.

## CLI

```
python3 dash.py ls [--json]                          전체 트리 개요
python3 dash.py next [--json]                        다음에 할 일 1건
python3 dash.py show <workspace-id|JIRA> [--json]
python3 dash.py add-category <name>
python3 dash.py add-workspace <category> <name>
         [--background .. --purpose .. --goal .. --considerations .. --jira ..]
python3 dash.py add-todo <title> (--category NAME | --workspace ID)
python3 dash.py add-subtask <todo-id> <title>
python3 dash.py move-todo <todo-id> --workspace <ID|none>
python3 dash.py set-status <todo|subtask|workspace> <id> <status>
python3 dash.py reorder <kind> [--scope ID] <id...>
python3 dash.py rm-category <id>                     비어 있을 때만
python3 dash.py done-today [--date YYYY-MM-DD] [--json]   그날 완료한 할일
```

`--json`은 Claude가 파싱하기 위한 것이다. 사람이 읽는 기본 출력과 분리한다.

`add-todo`는 `--category`와 `--workspace` 중 하나를 받는다. 둘 다 주면 `--workspace`가 이기고 카테고리는 워크스페이스의 것으로 정해진다 — 카테고리를 따로 받아봐야 어차피 덮어쓰기 때문이다.

## scope-guard 연결 (②로 이월)

**①에서는 scope-guard를 건드리지 않는다.** `scope_db.py`, `session-inject.sh`, `SKILL.md`, `scope.db` 전부 지금 그대로 둔다.

이월하는 이유는 두 가지다. 첫째, scope-guard는 매일 세션 시작마다 도는 물건이라 검증 안 된 `dash.db`에 물리면 KT 작업 세션 주입이 통째로 죽을 수 있다. 둘째, 흡수의 목적은 세션 주입이 대시보드 데이터를 쓰게 만드는 것인데 세션 주입 자체가 ②의 주제다. ①에서는 대시보드를 웹으로만 쓰므로 scope-guard가 어느 DB를 보든 체감 차이가 없다.

①이 준비하는 것은 `workspaces.jira_id` 컬럼 하나다. ②에서 `scope_db.py`를 `dash.db` 어댑터로 바꾸고 데이터를 옮길 때 이 컬럼이 연결점이 된다.

**감수하는 비용**: ① 기간 동안 KT-1530의 배경·목표가 대시보드와 `scope.db` 두 곳에 존재한다. 한쪽을 고치면 다른 쪽이 낡는다. ②를 바로 이어서 하지 않고 ①에서 몇 주 멈추면 두 데이터가 어긋난 채 남는다.

**②에서 옮길 때 주의할 점**: `set-steps`는 하위단계를 통째 교체하는 동작이라 할일 id가 재발급된다. `sessions`가 할일 id를 참조하기 시작하면 이 동작을 개별 갱신으로 바꿔야 한다.

## daily-todo 연결

완료한 할일을 Confluence 주간보고 표에 옮겨 적는 노동을 대시보드가 대신 덜어준다. 이게 없으면 ①은 Jira·daily-todo에 이은 세 번째 입력처가 되어 순수한 추가 노동으로만 남는다.

- `dash.py done-today [--date] [--json]` — 해당 날짜에 `completed_at`이 찍힌 할일을 워크스페이스와 함께 반환한다. 기본은 오늘(로컬 시간 기준).
- Confluence 쓰기는 대시보드가 하지 않는다. Claude 세션에서 `done-today --json` 결과를 받아 기존 `daily-todo:add` 스킬로 넘긴다. 대시보드가 Atlassian MCP에 직접 의존하면 의존성 0 원칙이 깨지고, 오프라인·인증만료 때 대시보드 자체가 못 뜬다.
- 오늘 완료 목록은 CLI 전용이다. 웹 보드의 "완료" 섹션은 날짜와 무관하게 다 끝낸 워크스페이스를 모아두는 자리이므로 역할이 다르다. 서버가 MCP를 호출할 수 없어 웹에 전송 버튼도 두지 않는다.
- `completed_at`은 status가 `done`으로 바뀔 때 찍고, `done`에서 벗어나면 지운다. `updated_at`으로 대신할 수 없다 — 완료 후 제목만 고쳐도 갱신되기 때문이다.

## 에러 처리

- **동시 쓰기** — 웹과 CLI가 같은 DB를 동시에 건드린다. WAL 모드 + `busy_timeout` 적용, 트랜잭션은 짧게 유지한다. 서버가 떠 있지 않아도 CLI는 독립 동작한다.
- **실시간 동기화 없음** — CLI가 바꾼 내용을 웹에서 보려면 새로고침한다. 1인용 도구에 폴링이나 WebSocket은 과하다.
- **검증 실패** — 카테고리 삭제 거부, 없는 id, FK 위반, 잘못된 status 값. CLI는 stderr 출력 + exit 1, API는 4xx + `{"error"}`. 웹은 그 메시지를 그대로 표시한다.
- **카테고리 정합성** — 할일에 워크스페이스를 지정하면 `category_id`를 워크스페이스의 것으로 덮어쓴다. 반대로 워크스페이스의 카테고리를 바꾸면 소속 할일의 `category_id`를 전부 함께 갱신한다. 어느 방향으로도 불일치 상태를 허용하지 않는다.
- **DB 없음** — 자동 생성 후 테이블 초기화. 카테고리가 비어 있으면 기본 6개(개발 / 운영 / 장애 대응 / 개발환경 개선 / 스킬 개발 / 프로세스 개선)로 시드한다. 이름 수정·삭제는 자유다.
- **포트 점유** — 어떤 포트가 막혔는지 명시하고 종료한다.
- **정적 파일 서빙** — `static/` 아래 여러 파일을 내주게 되면서 경로 traversal 표면이 새로 생긴다. 요청 경로를 정규화한 뒤 `static/` 밖으로 벗어나면 404로 거부한다. 허용 확장자는 `.html .css .js`로 제한한다. 디렉토리 목록은 내주지 않는다.

## 코딩 규칙

- 메서드 하나는 기능/역할 하나만 수행한다. HTTP 핸들러는 파싱·위임·직렬화까지만 하고 도메인 로직을 갖지 않는다.
- 주석은 결정 배경이 아니라 메서드의 역할이나 특이사항을 쓴다. 명사형 또는 음슴체, 한 문장, 마지막 문장 마침표 생략 가능. 결정 배경은 이 문서에 남긴다.
- 매직넘버 금지. 아래는 상수로 뺀다.

```python
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9080
BUSY_TIMEOUT_MS = 5000
UNASSIGNED_LABEL = "미분류"
SEED_CATEGORIES = ("개발", "운영", "장애 대응", "개발환경 개선", "스킬 개발", "프로세스 개선")
TODO_STATUSES = ("todo", "doing", "done")
WORKSPACE_STATUSES = ("active", "paused", "done")
```

- 짧고 명료하게. 모듈 하나는 자기 계층의 책임만 진다 — repository에 HTTP가 새어 들어오거나 진입점에 SQL이 들어가면 계층이 무너진 것이다.
- 파일이 300줄을 넘으면 책임이 섞였다는 신호로 보고 나눌 자리를 찾는다.

## 검증

`python3 -m tests` 한 방으로 전부 돈다. 프레임워크 없이 표준 `unittest`와 `assert`만 쓴다. 파일은 계층을 따라 나눈다 — `tests/test_repositories.py`, `tests/test_services.py`, `tests/test_cli.py`. 각 테스트는 임시 DB를 새로 만들어 서로 간섭하지 않는다.

아래 항목은 모두 덮는다.

1. 카테고리 → 워크스페이스 → 할일 → 하위할일 생성 및 조회
2. 할일을 워크스페이스에 배정하면 `category_id`가 워크스페이스의 것으로 동기화됨
3. 워크스페이스 기준 그룹핑에 미분류 그룹이 나오고, 할일 없는 그룹은 빠짐
4. 카테고리 기준 그룹핑에 미분류 할일도 포함됨
5. 재정렬 후 sort_order가 1..N으로 재부여됨
6. 비어 있지 않은 카테고리 삭제가 거부됨
7. 워크스페이스 삭제 시 소속 할일이 미분류로 남음
8. 할일 삭제 시 하위할일이 함께 사라짐
9. `next`가 최상위 active 워크스페이스의 첫 미완료 할일을 반환하고, `doing`을 `todo`보다 먼저 고름
10. `done` 전환 시 `completed_at`이 찍히고 `done`에서 벗어나면 지워짐
11. `done-today`가 해당 날짜 완료분만 반환함 (전날·다음날 완료분 제외)

12. 정적 파일 서빙이 화이트리스트 밖 경로를 거부함 (`../` 포함)

계층을 나눈 만큼 테스트도 계층에 붙는다. repository 테스트는 SQL과 정합성 규칙을, service 테스트는 트리 조립과 계획 로직을, CLI 테스트는 인자 파싱과 종료 코드를 본다. HTTP 계층은 라우팅과 예외→상태코드 매핑만 있어 별도 테스트 없이 수동 확인한다. 브라우저 화면도 수동 확인한다.

## 의도적 단순화

- ORM 없이 python3 표준 `sqlite3` 직접 사용. `scope_db.py`가 이미 이 방식으로 동작 중이다.
- 인증 없음. 기본 바인드가 localhost이고 LAN 노출은 명시적 옵션이다.
- 실시간 동기화 없음. 새로고침으로 충분하다.
- 순위는 정수 재부여. 항목 수가 수백 단위로 늘면 그때 다시 본다.
- 카테고리 우선순위 없음. 할일 의존성 필드 없음. 둘 다 규약과 수동 순위로 대신하고, 실제로 부족해지면 추가한다.
- 완료 항목 아카이브 없음. `done` 워크스페이스는 목록에서 숨겨질 뿐 계속 남는다. 쌓여서 거슬리면 그때 아카이브를 만든다.
- 프론트엔드 빌드 도구·프레임워크 없음. 브라우저 네이티브 ES 모듈로만 나눈다.
- 진입점이 repository를 직접 호출하는 경로를 허용한다. 모든 호출을 service로 통일하면 대칭적이지만 로직 없는 껍데기 계층이 생긴다.
- 변경 이력·감사 로그 없음. 필요해지면 그때 추가한다.
