# ③ 결정 대기 큐 — 확정 스펙

작성일: 2026-07-30 · 개정: 2026-08-03 · 상태: 결정 확정 (미구현) · 선행: `2026-07-30-session-mapping-spec.md`(②)
후속: `2026-07-30-autorun-spec.md`(④) — ④는 이 문서의 `--on-timeout block` 을 전제로 함

②가 확정한 것 중 이 문서가 올라서는 것: 세션 식별은 훅 stdin `session_id`(D1), CLI 는 인자 없이 `CLAUDE_CODE_SESSION_ID` 로 자기 세션을 앎(D2).

**2026-08-03 개정** — ②D2 가 master 에 없음(`CLAUDE_CODE_SESSION_ID` 참조 0건, `classify`·`link-todo`·`finish`·`statusline` 은 모두 `session` 위치인자를 받음). 따라서 `ask` 도 **현 CLI 규약대로 세션 인자를 받음**: `dash.py ask <session> "<질문>" …`. ② 가 구현되면 인자를 생략 가능한 형태로 되돌린다(그때 고칠 곳은 이 명령 하나).

| 항목 | 무엇이 바뀌었나 |
| --- | --- |
| 답변 엔드포인트 | `POST /api/decisions/<id>/answer` → `PATCH /api/decisions/<id>` (D4). `server.py:route` 는 `/api/<head>/<id>` 두 세그먼트만 파싱하고 POST 핸들러는 `item_id` 를 받지 않음 |
| 선제조건 | 조건 미충족은 큐에 묻지 않음. 질문이 아니라 상태이므로 할일을 `waiting` 으로 내림 (⑥, D6) |
| 화면 자리 | 보드가 탭 구조로 바뀌었음(좌측 4탭 + 보드 서브탭). 배지·목록은 보드 탭의 세션 패널 옆 (D4) |

## (a) 해결하려는 문제

1. **판단 요청이 세션 안에 갇힘.** `AskUserQuestion` 은 그 세션 터미널을 보고 있어야 답할 수 있음. 세션이 3~4개 동시에 돌 때 어느 창이 무엇을 기다리는지 밖에서 알 수 없음.
2. **자리를 비우면 대기 시간이 전부 사장됨.** 5분 뒤에 답할 수 있는 질문 때문에 세션이 몇 시간 멈춰 있음.
3. **막힌 세션의 처리가 세션마다 다름.** 어떤 세션은 물어보고 멈추고, 어떤 세션은 임의 가정으로 계속 감. 이 문서를 쓰는 세션도 "권장안으로 네가 선택해" 를 받아 진행 중임 — 규칙이 없어 매번 사용자가 즉흥으로 정해주고 있음.
4. **④의 전제가 없음.** 자율 세션이 판단에 막혔을 때 갈 곳이 없으면 ④는 추측으로 코드를 쌓거나 죽음.

## (b) 확정한 결정

### D1. 큐는 대시보드 DB(`decisions` 테이블)에 둠

새 채널(슬랙·메일·푸시)을 만들지 않음. 근거 — 사람이 보는 웹 UI 와 Claude 가 쓰는 CLI 가 같은 sqlite 를 이미 공유하고, 세션 영역에 2초 폴링이 이미 있음. 알림 경로를 새로 붙이는 것보다 이미 열려 있는 화면에 얹는 것이 싸고 오프라인에서도 동작함.

```sql
decisions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id INTEGER REFERENCES sessions(id),   -- 물어본 세션. NULL 허용(세션이 정리된 뒤에도 남김)
  todo_id INTEGER REFERENCES todos(id),         -- 어느 할일에서 나온 질문인지. NULL 허용
  question TEXT NOT NULL,
  options TEXT NOT NULL,                        -- JSON 배열 ["A안 …","B안 …"]
  default_index INTEGER NOT NULL,               -- 0-based. 필수
  on_timeout TEXT NOT NULL,                     -- default | block
  status TEXT NOT NULL,                         -- pending | answered | defaulted | blocked | cancelled
  answer_index INTEGER,
  answer_note TEXT,
  asked_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,                     -- asked_at + wait
  resolved_at TEXT);
```

날짜는 ISO8601 UTC (①과 동일).

### D2. 선택형 + 기본값 필수. 자유서술 답변 없음

옵션 2~4개, `--default` 로 그중 하나를 반드시 지정. 사용자는 옵션을 고르고 필요하면 메모(`answer_note`)를 덧붙임.

근거 — 자유서술 답변은 세션이 문장을 해석해야 하고, 해석이 틀리면 되묻기 루프가 생김. 기본값 없는 질문을 허용하면 "만료 시 무엇을 할지"가 매번 미정이 되어 문제 3이 그대로 남음. 기본값을 강제하면 질문을 만드는 쪽이 먼저 판단을 하게 됨.

메모로 옵션 밖의 지시가 들어오면 세션은 그 메모를 우선함 — 옵션은 기본 경로, 메모는 사용자 개입.

### D3. 대기 방식 = 짧은 블로킹 + 만료 정책을 호출자가 지정

```bash
dash.py ask "락을 테이블 단위로 잡을지 행 단위로 잡을지" \
  --option "테이블 단위 (안전, 처리량 손실)" \
  --option "행 단위 (처리량 유지, 구현 복잡)" \
  --default 0 --wait 300 --on-timeout default
```

stdout 한 줄로 결과를 돌려줌. 세션은 이 값만 보고 진행함.

| 출력 | 의미 | 세션이 할 일 |
| --- | --- | --- |
| `answered:<index>` (+ 메모가 있으면 다음 줄) | 사용자가 고름 | 그 옵션으로 진행 |
| `defaulted:<index>` | 만료, `on_timeout=default` | 기본값으로 진행하고 결과 보고에 그 사실을 한 줄 적음 |
| `blocked:<id>` | 만료, `on_timeout=block` | 그 작업을 중단하고 다음 일로 넘어감. 재개는 사용자가 |

`--wait` 상한 = **540초**. 근거 — Bash 도구 타임아웃 상한이 600초임. 그보다 길게 기다리면 도구가 먼저 끊겨 큐 항목만 `pending` 으로 남고 세션은 답을 못 받음. 기본 300초.

| 상황 | `--on-timeout` | 근거 |
| --- | --- | --- |
| 사용자가 앞에 있거나 곧 돌아오는 대화형 세션 | `default` | 취향·경로 선택은 기본값으로 가도 되돌리기 비용이 작음 |
| ④ 자율 세션 | `block` | 사람이 없는 동안 추측으로 코드를 쌓는 것이 가장 비싼 실패. 막히면 멈추고 다음 할일로 |

### D4. 답변 경로는 웹 원클릭이 주(主), CLI 가 보조

- 웹: **보드 탭**의 세션 패널(`#session-panel`) 위에 "결정 대기 N" 배지 + 목록. 옵션 버튼을 누르면 즉시 답변. 메모는 접힌 입력창
- CLI: `dash.py answer <id> <index> [--note "…"]`, `dash.py decisions [--json]`
- 브라우저 탭 title 에 대기 건수를 붙임 (`(2) 작업 대시보드`) — 탭을 안 보고 있어도 눈에 들어옴. 지금 `document.title` 을 건드리는 코드가 없으므로 소유자를 `main.js` 의 `showTab` 한 곳으로 정함(탭 전환이 히스토리 라우팅과 엮여 있어 두 곳에서 쓰면 서로 덮음)
- 답변 엔드포인트는 `PATCH /api/decisions/<id>` (body `{answer_index, answer_note?}`). `server.py:route` 가 `/api/<head>/<id>` 두 세그먼트만 파싱하고 세 번째 세그먼트를 버리며, POST 분기는 `item_id` 를 받지 않기 때문 — 라우터 모양을 바꾸지 않고 얹는다

폴링은 **새로 만들지 않음**. `GET /api/sessions` 응답에 `decisions` 배열을 함께 실음. 근거 — 폴링 루프를 하나 더 만들면 요청이 2배가 되는데, 두 데이터가 같은 2초 주기로 같은 영역에 렌더됨. 엔드포인트 이름이 내용보다 좁아지는 대가를 받아들이고 주석으로 남김(`# ponytail: 라이브 영역 응답. 폴링 1개를 유지하려고 sessions 에 얹음`).

### D5. 상태 전이

| 현재 | 조건 | 다음 |
| --- | --- | --- |
| — | `ask` 등록 | `pending` |
| `pending` | 사용자가 옵션 선택 | `answered` |
| `pending` | `expires_at` 경과 + `on_timeout=default` | `defaulted` |
| `pending` | `expires_at` 경과 + `on_timeout=block` | `blocked` |
| `pending` | 물어본 세션이 `ended` | `cancelled` |
| `defaulted`·`blocked`·`answered` | — | 종료. 되돌리지 않음 |

만료 판정은 조회 시점에 함(`GET /api/sessions`·`dash.py decisions`·`ask` 의 대기 루프). 크론을 새로 만들지 않음 — ②의 세션 정리와 같은 방식.

**자동 롤백 없음.** `defaulted` 로 진행한 뒤 사용자가 다른 답을 원하면 새 지시로 고침. 이미 만들어진 변경을 큐가 되돌리려 하면 세션 밖에서 코드 상태를 추적해야 하는데, 그 복잡도가 얻는 것보다 큼. `defaulted` 항목은 목록에서 노란색으로 남아 사후 검토가 됨.

### D6. 무엇을 큐에 올리는지 — 세션 쪽 규칙

주입 블록의 지침에 이 표를 넣음(`session_link.py` 의 가이드 문자열).

| 상황 | 처리 |
| --- | --- |
| 사용자가 앞에 있고 즉답이 필요 | `AskUserQuestion` (큐 안 씀) |
| 자리 비움·백그라운드 잡·④ 자율 세션 | ③ 큐 |
| 되돌릴 수 없는 행위(커밋·푸시·외부 전송·삭제·배포) | 큐 필수 + `--on-timeout block` |
| 스타일·이름·문구 같은 취향 | 큐 안 씀. 기본값으로 진행하고 결과에 한 줄 보고 |
| 사용자가 이미 "권장안으로 네가 정해라" 를 말한 범위 | 큐 안 씀 |
| 할일의 선제조건이 아직 안 풀림 | 큐 안 씀. `dash.py set-status todo <id> waiting` 으로 내리고 다음 할일로 (⑥D2). 조건은 물어서 결정할 것이 아니라 기다려야 하는 사실이므로, 큐에 올리면 만료·기본값 정책이 붙어 "조건이 안 풀렸는데 진행" 이 가능해짐 |

### D7. 큐가 비면 아무것도 표시하지 않음

배지·목록 영역 전체를 숨김. 대기 0건일 때 빈 상자를 보여주는 것은 소음.

## (c) 의도적으로 안 하는 것

- 자유서술 답변 (D2)
- 자동 롤백 (D5)
- 푸시·메일·슬랙 알림 — 브라우저 탭 title 까지만. 외부 채널은 인증·상시 프로세스를 부름
- `AskUserQuestion` 대체 — 사용자가 앞에 있으면 그게 더 빠름. 큐는 "밖에서 답할 수 있게" 하는 것뿐
- 질문 우선순위·마감·에스컬레이션 — 목록은 등록 순서
- 세션 간 같은 질문 병합·중복 감지 — 두 세션이 비슷한 걸 물으면 두 건으로 남김
- 결정 이력 통계(무엇을 몇 번 물었는지, 기본값 채택률) — 데이터만 남기고 화면은 안 만듦
- 다중 사용자·권한 — 1인용
- 대기 중 세션을 `waiting` 상태로 따로 표시 — ②의 3상태(`working`/`idle`/`ended`)를 늘리지 않음. `ask` 로 대기하는 동안은 `working` 임

## (d) 구현 시 건드릴 파일 경계

| 파일 | 변경 |
| --- | --- |
| `app/db.py` | `decisions` 테이블 추가 |
| `app/repositories/decisions.py` | 신규 — 등록·답변·목록·만료 판정 |
| `app/services/decisions.py` | 신규 — `ask` 의 대기 루프(폴링 + 만료 처리), 결과 문자열 조립 |
| `dash.py` | `ask`, `answer`, `decisions` 명령 |
| `server.py` | `PATCH /api/decisions/<id>`, `GET /api/sessions` 응답에 `decisions` 추가 |
| `static/js/decisions.js` | 신규 — 배지·목록·옵션 버튼 |
| `static/js/main.js` | 탭 title 의 대기 건수 (D4) |
| `static/index.html`, `static/css/app.css` | 보드 탭의 결정 영역 자리와 스타일. `tests/test_css_tokens.py` 가 raw px·미정의 토큰을 막으므로 토큰만 사용 |
| `app/services/session_link.py` | D6 규칙을 주입 지침에 추가 |
| `app/constants.py` | `DECISION_STATES`, `WAIT_DEFAULT_SEC=300`, `WAIT_MAX_SEC=540`, `DECISION_POLL_SEC=2`, `DECISION_OPTIONS_MAX=4` |
| `tests/test_decisions.py` | 신규 |

**건드리지 않음** — `sessions` 테이블 스키마(외래키로만 참조), `categories`·`workspaces`·`todos`·`subtasks`, `hooks/dash_hook.py`, `app/services/{board,planning,usage}.py`, `~/.claude/*`.

**착수 전 확인** — `dash.py`·`server.py`·`app/constants.py`·`static/*` 는 다른 세션(사용량 대시보드)이 동시에 고치고 있음. `git status`·`git log` 로 반영 여부 확인 후 착수.

## 검증

`python3 -m tests` 에 `tests/test_decisions.py` 합류.

1. `ask` 등록 → `pending`, `expires_at` = `asked_at` + wait
2. 옵션이 1개거나 5개 이상 → 에러
3. `--default` 가 옵션 범위 밖 → 에러
4. `--wait` 가 540 초과 → 540 으로 잘림(동작을 그렇게 확정)
5. 대기 중 다른 경로에서 `answer` → `answered:<index>` 출력, 메모 포함
6. 만료 + `on_timeout=default` → `defaulted:<index>`, 상태 `defaulted`
7. 만료 + `on_timeout=block` → `blocked:<id>`, 상태 `blocked`
8. 물어본 세션이 `ended` → `cancelled`, 목록에서 빠짐
9. `GET /api/sessions` 응답에 `pending` 항목만 실림
10. 이미 해결된 항목에 `answer` → 에러, 상태 불변
11. `PATCH /api/decisions/<id>` 가 답변을 반영하고, id 없이 부르면 `Validation`(400)

수동 확인 — 브라우저에서 옵션 버튼을 누른 뒤 대기 중인 CLI 가 2초 안에 결과를 출력하는지.
