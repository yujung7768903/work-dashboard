# 세션 소속을 할일 하나로 — 확정 스펙

작성일: 2026-08-03 · 상태: 결정 확정 · 선행: `2026-07-30-session-mapping-spec.md`(②)

②의 D1·D2 를 대체하지 않음. 세션이 무엇에 속하는지를 정하는 부분만 바꾸는 델타 문서임. 충돌 시 이 문서가 우선.

## (a) 해결하려는 문제

`sessions.workspace_id` 와 `todos.workspace_id` 가 각각 존재하고 서로를 모름. 세션을 워크스페이스로 분류해도 보드는 `todos.workspace_id` 로만 그리므로 그 워크스페이스에 아무것도 나타나지 않음.

| 분류 경로 | 지금 | 결과 |
| --- | --- | --- |
| `dash.py classify --workspace 3` | `sessions.workspace_id` 만 세팅 | 보드에 안 보임. Claude 가 `add-todo` 를 따로 해야 함 |
| 웹 팝업에서 워크스페이스 선택 | `classify_by_ids` + `session_todo.ensure_from_session` | 할일이 생김 (세 가지 None 조건에 걸리면 안 생김) |

같은 "분류" 라는 말이 두 경로에서 다른 일을 함. 소속이 두 군데 있는 것이 원인임.

## (b) 확정한 결정

### E1. 세션의 소속은 할일뿐. `sessions.workspace_id` 제거

`session_todos` 가 유일한 매핑임. 세션의 워크스페이스는 **연결된 할일에서 파생**함 — 여러 개면 가장 최근 연결된 할일 기준.

`sessions.category_id` 는 남김. 단발 조회 세션은 할일을 만들지 않는 것이 규칙이라, 카테고리마저 없으면 영원히 "분류 전" 으로 남음.

### E2. 분류는 할일 연결까지 끝나야 완료

"워크스페이스는 정해졌는데 할일이 아직 없는 세션" 상태를 허용하지 않음. 그 상태를 담을 칸이 없어짐.

| 단계 | 하는 일 |
| --- | --- |
| 1 | `dash.py classify --workspace <id>` — 카테고리를 워크스페이스에서 정해 세션에 넣고, 그 워크스페이스의 **미연결 todo/doing 후보**를 출력 |
| 2 | Claude 가 후보에서 고르면 `link-todo <todo-id>`, 없으면 `add-todo <제목> --workspace <id>` 후 연결 |

후보 중 무엇이 이 세션의 작업인지는 의미 판단이라 코드가 정하지 않음. 코드는 후보를 좁혀 주기만 함 — 문자열 유사도 자동 매칭은 오탐이 커서 두지 않음.

### E3. 브랜치 Jira 자동 분류는 첫 프롬프트로 미룸

`attach_by_branch` 는 `SessionStart` 에서 도는데 그 시점에는 첫 지시가 없어 할일 제목을 지을 원문이 없음. 워크스페이스만 정해진 중간 상태를 만들지 않기 위해, 카테고리만 넣고 할일은 첫 지시가 들어온 뒤(`UserPromptSubmit`) 만듦.

### E4. 웹 팝업은 지금대로 자동 생성

팝업에서 워크스페이스를 고르는 자리에는 Claude 가 없어 후보 탐색(의미 판단)을 할 수 없음. 후보 목록을 보여주고 고르게 하는 UI 는 두지 않고, 기존처럼 지시 원문으로 할일을 만들어 연결함. `ensure_from_session` 이 세션에서 워크스페이스를 못 읽게 되므로 인자로 받음.

## (c) 의도적으로 안 하는 것

- 웹 팝업의 후보 할일 선택 UI — 필요해지면 그때. 지금은 자동 생성으로 충분함
- 세션 하나에 워크스페이스가 여럿 걸릴 때의 트리 표시 — 가장 최근 연결 하나만 보여줌
- 기존 세션의 `workspace_id` → 할일 역생성 마이그레이션 — 카테고리는 이미 워크스페이스에서 파생돼 들어가 있어 잃는 정보가 없음

## (d) 건드릴 파일 경계

| 파일 | 변경 |
| --- | --- |
| `app/db.py` | `sessions` 스키마에서 `workspace_id` 제거 + 기존 DB `ALTER TABLE sessions DROP COLUMN workspace_id` |
| `app/repositories/sessions.py` | `classify`·`classify_by_ids` 에서 저장 제거(카테고리 결정에만 사용), `list_active`·`find`·`get` 의 `workspace_name` 을 `session_todos JOIN todos` 파생으로, `cwds_by_workspace` 를 같은 조인으로 |
| `app/services/session_link.py` | `render_context` 분기를 파생 워크스페이스로, `attach_by_branch` 를 카테고리만 넣도록 |
| `app/services/session_todo.py` | `ensure_from_session(con, session_row_id, workspace_id, ...)` |
| `dash.py` | `_scope_from_session` 을 연결 할일에서 파생, `classify --workspace` 가 후보 출력 |
| `server.py` | `PATCH /api/sessions/<id>` 가 워크스페이스를 `ensure_from_session` 에 넘김 |
| `static/js/sessions.js` | 세션 줄의 워크스페이스 표시가 파생값을 쓰도록 |

## 검증

1. `classify --workspace` 가 미연결 todo/doing 후보를 출력하고, 세션에는 카테고리만 남음
2. `link-todo` 로 연결한 뒤 세션 목록·주입 블록의 워크스페이스가 그 할일의 것으로 나옴
3. 할일이 없는 세션은 주입 블록이 "분류 전" 임 (카테고리만 있어도)
4. 할일 두 개를 서로 다른 워크스페이스에서 연결하면 가장 최근 것이 보임
5. 웹 팝업 분류가 예전처럼 할일을 만들고 연결함
6. `workspace_id` 가 있던 기존 DB 를 열면 컬럼이 사라지고 카테고리는 유지됨
