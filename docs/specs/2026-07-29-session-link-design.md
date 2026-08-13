# ② Claude 세션 연동 설계

작성일: 2026-07-29 · 상태: 설계 확정 (미구현) · 선행: `2026-07-29-work-dashboard-design.md`(①, 구현 완료)

## 배경

①로 카테고리 > 워크스페이스 > 할일 > 하위할일 데이터 모델과 로컬 웹·CLI가 만들어졌다. 하지만 대시보드는 아직 손으로 적는 곳이다. 원래 이 도구를 만든 이유는 Claude 세션마다 같은 맥락을 반복 설명하지 않는 것과, 여러 세션을 동시에 돌릴 때 무엇이 어디까지 갔는지 아는 것이었다.

세션 식별 방법은 확인됐다. Claude Code 훅은 stdin JSON으로 `session_id`, `transcript_path`, `cwd`를 준다(`CLAUDE_SESSION_ID` 환경변수도 폴백으로 존재). 이미 모든 훅 이벤트에 물려 있는 `claude-office-hooks`가 이 필드들을 읽어 쓰고 있다. tmux `capture-pane`으로 화면을 긁을 필요가 없다.

## 목적

세션이 스스로 어느 카테고리·워크스페이스의 작업인지 분류하고, 워크스페이스의 배경·목적을 받아 일하게 한다. 그리고 무엇이 돌고 있는지 대시보드에서 바로 보이게 한다.

## 목표

- 세션 자동 등록 (`session_id`·`cwd`·브랜치)
- 1차 카테고리 분류 (필수), 2차 워크스페이스 분류 (선택, 사용자 확인 후)
- 워크스페이스 확정 시 배경·목적·목표·고려사항 주입
- 활성 세션의 분류·상태·마지막 지시를 대시보드에 실시간 표시
- 할일은 필요할 때만 생성하고 세션에 연결
- scope-guard 흡수 (①에서 이월한 항목)

## ①의 결정을 뒤집는 부분

① 스펙은 "실시간 동기화 없음 — 1인용 도구에 폴링/WebSocket은 과하다"고 못 박았다. ②는 이를 되돌린다.

근거가 바뀌었다. ①에서는 사람만 편집했으므로 새로고침이 충분했다. ②부터는 **훅이 사용자 조작 없이 DB를 바꾼다.** 세션이 붙고 상태가 변하는 것을 새로고침으로 확인해야 하면 목적을 잃는다.

단 폴링은 **세션 영역에만** 적용한다. 보드의 나머지(그룹·할일·워크스페이스 상세)는 여전히 새로고침이다. 편집 중인 입력이 폴링 때문에 날아가는 일을 만들지 않는다.

## 범위에서 뺀 것

| 후속 | 내용 |
|------|------|
| ③ 결정 대기 큐 | Claude가 판단을 요청하고 사용자가 목록에서 즉시 결정 |
| ④ 자율 실행 | 스스로 다음 일을 찾아 수행, 세션 리밋 시 대기 후 재개 |

세션 리밋·비정상 종료 감지는 ④의 주제다. ②는 `last_seen_at`이 오래된 세션을 `ended`로 간주하는 것까지만 한다.

도구 호출 단위 진행 상황(현재 실행 중인 도구·파일·토큰)은 넣지 않는다. `PreToolUse`/`PostToolUse`마다 DB를 쓰면 부하와 소음이 크고, 상태 판정에는 `UserPromptSubmit`~`Stop` 구간으로 충분하다.

## 용어

- **분류 전** — 세션의 `category_id IS NULL`. 아직 어느 작업인지 정해지지 않은 상태. 해소해야 하는 상태다.
- **미분류** — 할일의 `workspace_id IS NULL`. ①에서 정의한 정상 상태. 세션의 `workspace_id IS NULL`도 문제가 아니다.

두 용어를 섞지 않는다.

## 데이터 모델

기존 4테이블(`categories`, `workspaces`, `todos`, `subtasks`)은 변경하지 않는다. ①에서 약속한 대로 추가만 한다.

```sql
sessions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  claude_session_id TEXT NOT NULL UNIQUE,          -- 훅이 주는 session_id
  cwd TEXT,
  git_branch TEXT,
  category_id INTEGER REFERENCES categories(id),   -- 1차 분류. NULL = 분류 전
  workspace_id INTEGER REFERENCES workspaces(id),  -- 2차 분류. NULL = 워크스페이스 미배정
  state TEXT NOT NULL DEFAULT 'idle',              -- working | idle | ended
  last_prompt TEXT,                                -- 마지막 사용자 지시 한 줄
  started_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ended_at TEXT);

session_todos(
  session_id INTEGER NOT NULL REFERENCES sessions(id),
  todo_id INTEGER NOT NULL REFERENCES todos(id),
  created_at TEXT NOT NULL,
  PRIMARY KEY(session_id, todo_id));
```

날짜는 ISO8601 UTC (①과 동일).

### 설계 판단

**`session_todos`를 연결 테이블로 둔다.** 한 세션이 할일을 여러 개 만들 수 있어 `sessions.todo_id` 하나로는 못 담는다. `todos`에 컬럼을 추가하면 기존 테이블을 건드리게 된다.

**`state`는 세 값뿐이다.** `working`은 사용자 지시를 받아 처리 중(`UserPromptSubmit`~`Stop` 사이), `idle`은 입력 대기, `ended`는 종료. 리밋·오류 같은 세부 상태는 ④에서 다룬다.

**`last_prompt`은 한 줄로 잘라 저장한다.** 전문은 `transcript_path`에 있고, 목록에서 구분할 용도로만 쓴다.

## 아키텍처

①의 3계층을 그대로 따른다. 훅도 진입점이므로 도메인 로직을 갖지 않는다.

```
hooks/dash_hook.py              훅 단일 진입점. `dash_hook.py <event>` 로 분기
app/repositories/sessions.py    세션 등록·분류·상태 갱신·정리
app/services/session_link.py    주입 컨텍스트 조립
static/js/sessions.js           활성 세션 렌더 + 2초 폴링
tests/test_sessions.py
```

수정 대상: `app/constants.py`(상수 추가), `app/db.py`(스키마 2테이블 추가), `dash.py`·`server.py`(명령·엔드포인트 추가), `static/index.html`·`static/js/board.js`(세션 영역 자리), `README.md`(실행·롤백 절차), `~/.claude/settings.json`(훅 등록·scope-guard 훅 제거).

훅을 이벤트별 파일 4개로 쪼개지 않는다. `claude-office-hook <event>`가 이미 같은 단일 진입점 패턴이고, 각 분기가 얇다(파싱 → repository 호출 → 주입 문자열 출력).

## 훅 구성

`~/.claude/settings.json`의 `hooks`에 등록한다. 기존 `claude-office-hook` 항목과 공존한다.

| 이벤트 | 하는 일 |
| -------- | --------- |
| `SessionStart` | 세션 등록(`session_id`·`cwd`·브랜치) + 컨텍스트 주입 |
| `UserPromptSubmit` | `working` 전환, `last_prompt` 저장, 분류 전이면 분류 지시 재주입 |
| `Stop` | `idle` 전환, `last_seen_at` 갱신 |
| `SessionEnd` | `ended` 전환, `ended_at` 기록 |

타임아웃은 2초로 준다.

## 주입 내용

두 갈래다.

**(A) 브랜치에서 Jira ID가 나오고 그 `jira_id`를 가진 워크스페이스가 있으면** — 확인 없이 바로 확정한다. 그 워크스페이스의 배경·목적·목표·고려사항과 소속 할일 목록을 주입한다. scope-guard가 이미 이 신뢰도로 동작해왔으므로 여기서 다시 묻는 것은 군더더기다.

**(B) 그 외** — 카테고리 목록, `active` 워크스페이스 목록(이름 + 목표 한 줄), `cwd`, 분류 지시를 주입한다.

주입 형식은 ①의 scope-guard 블록과 같은 모양을 쓴다.

```
<work-dashboard session="<session_id>" state="classified">
워크스페이스: KT 동시성 이슈 해결 (개발) [KT-1530]
배경: ...
목적: ...
목표: ...
고려사항: ...
할일:
  1. [doing] 프론트/백엔드 1차 반영 범위 정합성 확인
  2. [todo] ...
지침: 이 세션은 위 워크스페이스 작업이다. 배경·목적에 맞게 진행하고 범위를 벗어나면 확인받는다.
</work-dashboard>
```

분류 전일 때:

```
<work-dashboard session="<session_id>" state="unclassified">
현재 위치: /home/user/work/kt-cms-server (브랜치 master)
카테고리: 개발 / 운영 / 장애 대응 / 개발환경 개선 / 스킬 개발 / 프로세스 개선
진행 중 워크스페이스:
  1. KT 동시성 이슈 해결 (개발) — 1차: 잠금 구조 개편으로 동시 저장 충돌 차단
  2. 작업 대시보드 (개발환경 개선) — 1차: 4계층 관리와 웹 UI 완성
지침: 아래 분류 절차를 이번 세션에서 한 번 수행한다.
</work-dashboard>
```

## 분류 절차

첫 질문을 받은 Claude가 수행한다. 셸 훅은 질문 내용을 이해할 수 없으므로 훅이 분류할 수 없다.

1. **카테고리 결정 (필수)** — `cwd`와 질문 내용으로 판단한다. 사용자 확인을 받지 않는다.
2. **워크스페이스 추정 (선택)** — 관련된 `active` 워크스페이스가 있다고 판단되면 **사용자에게 확인한다.** 확정되면 등록하고, 그 워크스페이스의 배경·목적·목표를 읽어 이후 작업에 반영한다.
3. 관련된 워크스페이스가 없으면 카테고리만 등록하고 넘어간다.

등록은 CLI로 한다.

```
python3 dash.py classify <session-id> --category 개발 [--workspace 1]
```

### 할일 생성 규칙

- 코드·문서를 바꾸거나, 여러 턴에 걸치거나, 결론·산출물이 남는 작업 → 할일을 만들고 세션에 연결한다.
- 단발 조회·설명·사용법 질문 → 만들지 않는다.
- 사용자가 지시하면 판단하지 않고 만든다.

```
python3 dash.py add-todo "제목" --workspace 1
python3 dash.py link-todo <session-id> <todo-id>
```

### 분류 누락 보완

지시 주입은 강제가 아니다. Claude가 분류를 건너뛸 수 있다.

- `UserPromptSubmit`이 분류 전 상태면 매 프롬프트마다 분류 지시를 재주입한다. 분류되면 멈춘다.
- 그래도 새는 경우가 있으므로 대시보드에 **"분류 전 세션 N건"**을 경고로 표시한다.

이 두 장치로 완전히 막지는 못한다. 남는 누락은 사용자가 대시보드에서 손으로 고친다(`PATCH /api/sessions/<id>`).

## 화면

탭을 추가하지 않는다. 보드 상단 "다음에 할 일" 아래에 활성 세션 영역을 둔다.

```
┌──────────────────────────────────────────────────────────┐
│ 다음에 할 일 ▸ KT 동시성 이슈 해결 / 락 재설계 초안 잡기    │
├──────────────────────────────────────────────────────────┤
│ 돌고 있는 세션 3                        분류 전 1건 ⚠     │
│ ● KT 동시성 이슈 해결   (개발)   modifymode 응답 확인해줘  │
│ ○ 작업 대시보드         (개발환경 개선)  UI 확인했으니 다음… │
│ ○ ―                     (분류 전)  vim 스크롤 어떻게 해     │
└──────────────────────────────────────────────────────────┘
```

- `●` working / `○` idle
- 워크스페이스가 없으면 `―`, 분류 전이면 카테고리 자리에 `(분류 전)`
- 줄을 클릭하면 그 워크스페이스 상세 탭으로 이동한다. 워크스페이스가 없으면 클릭해도 아무 일도 없다
- 분류 전 건수는 따로 세어 경고로 띄운다

`sessions.js`가 2초마다 `GET /api/sessions`를 폴링해 이 영역만 다시 그린다.

## HTTP·CLI

```
GET   /api/sessions          활성 세션 목록 + 분류 전 건수. 폴링 대상
PATCH /api/sessions/<id>     {category_id?, workspace_id?} 분류 수정

python3 dash.py sessions [--json]
python3 dash.py classify <session-id> --category NAME [--workspace ID]
python3 dash.py link-todo <session-id> <todo-id>
```

`classify`의 `<session-id>`는 `claude_session_id`(훅이 주는 값)를 받는다. Claude가 주입된 블록에서 그 값을 그대로 쓴다. `PATCH /api/sessions/<id>`의 `<id>`는 내부 정수 id다 — 대시보드가 목록에서 받은 값을 그대로 쓴다.

`GET /api/sessions` 응답:

```json
{
  "unclassified_count": 1,
  "sessions": [
    {"id": 1, "claude_session_id": "…", "state": "working",
     "category_name": "개발", "workspace_id": 1,
     "workspace_name": "KT 동시성 이슈 해결",
     "last_prompt": "modifymode 응답 확인해줘", "last_seen_at": "…"}
  ]
}
```

## 정리 정책

최근 7일 최상위 세션이 119건, 하루 평균 17건이었다. 상당수가 단발 질문이다. 전부 남기면 목록이 며칠 만에 못 볼 물건이 된다.

- 목록에는 `working`/`idle`만 나온다. `ended`는 표시하지 않는다.
- `ended`이고 연결된 할일이 없으면 **7일 후 삭제**한다. 단발 질문 세션은 흔적 없이 사라진다.
- 할일이 연결된 세션은 유지한다. 단 **②에서는 이 기록을 보여주는 화면이 없다.** 남기는 이유는 나중에 주간보고 집계와 ④ 자율 실행이 "이 할일을 어느 세션이 했는지" 되짚을 때 쓰기 위함이다. 지금 당장 쓸 데가 없다는 것을 인정하고 남긴다.
- `last_seen_at`이 **24시간**을 넘은 `idle`은 `ended`로 간주한다. 터미널이 죽으면 `SessionEnd`가 오지 않는다.
- 정리는 `dash.py sessions`와 `GET /api/sessions` 호출 시 함께 수행한다. 크론을 새로 만들지 않는다.

상수로 뺀다.

```python
STALE_IDLE_HOURS = 24
ENDED_RETENTION_DAYS = 7
SESSION_STATES = ("working", "idle", "ended")
STATE_WORKING, STATE_IDLE, STATE_ENDED = SESSION_STATES
HOOK_EVENTS = ("SessionStart", "UserPromptSubmit", "Stop", "SessionEnd")
LAST_PROMPT_MAX_CHARS = 120
POLL_INTERVAL_MS = 2000
```

## scope-guard 흡수

①에서 이월한 항목이다. 지금 하는 이유는 scope-guard도 `SessionStart`에 컨텍스트를 주입하기 때문이다. 통합하지 않으면 같은 내용이 두 번 들어간다.

- `scope_db.py`를 `dash.db` 어댑터로 교체한다. `get <JIRA>`는 `workspaces.jira_id`로 워크스페이스를 찾아 기존 `<scope-guard>` 블록 형식을 그대로 렌더한다. 하위단계 자리에는 그 워크스페이스의 할일이 들어간다.
- `~/.claude/settings.json`에서 scope-guard의 `SessionStart` 훅(`session-inject.sh`)을 **제거**한다. `dash_hook.py`가 주입을 담당한다.
- `SKILL.md`는 유지한다. `/scope-guard` 로 목표를 세우면 `dash.db`의 워크스페이스에 저장된다.
- 기존 `~/.claude/scope-guard/scope.db`에는 KT-1530 한 건이 있고 대시보드에 이미 같은 워크스페이스가 있다. 마이그레이션하지 않고 `scope.db.bak`으로 백업만 한다.

**롤백** — `dash_hook.py`에 문제가 생기면 `settings.json`에서 `dash_hook` 항목을 지우고 `session-inject.sh` 항목을 되살린다. `scope.db.bak`을 `scope.db`로 복원하면 ① 이전 상태로 돌아간다. 이 절차를 `README.md`에 적는다.

## 에러 처리

**훅은 절대 작업을 막지 않는다.** 모든 실패에서 `exit 0`, 무출력으로 끝낸다. DB 잠김, 경로 없음, JSON 파싱 실패, 예상 못한 예외 전부 포함한다. 대시보드 버그로 Claude 세션이 안 열리는 것이 최악의 실패다.

- 훅 타임아웃 2초. 초과하면 Claude Code가 끊는다.
- 같은 `claude_session_id` 재등록(resume) → 기존 행을 갱신하고 **분류는 유지**한다.
- `classify`에 없는 카테고리·워크스페이스를 주면 `NotFound`. CLI는 stderr + exit 1.
- 워크스페이스를 지정하면 카테고리는 그 워크스페이스의 것으로 덮어쓴다. ①의 할일 정합성 규칙과 같은 방향이다.
- 폴링 실패 → 에러 배너를 띄우고 폴링은 계속한다. 서버를 껐다 켜도 화면이 스스로 복구된다.
- 세션이 지워진 뒤 늦게 도착한 훅 이벤트 → 새 행으로 등록하지 않고 조용히 무시한다.

## 검증

`python3 -m tests`에 `tests/test_sessions.py`를 합류시킨다.

1. 등록·재등록(resume) 시 분류가 유지됨
2. `working`/`idle`/`ended` 전이
3. `last_prompt` 저장·갱신, `LAST_PROMPT_MAX_CHARS` 초과 시 잘림
4. 카테고리만 분류 / 카테고리+워크스페이스 분류
5. 워크스페이스 지정 시 카테고리가 워크스페이스의 것으로 덮어써짐
6. 브랜치 Jira → 워크스페이스 자동 확정 주입
7. 분류 전 주입에 카테고리 목록과 active 워크스페이스가 들어감
8. `session_todos` 연결과 중복 연결 무시
9. 활성 목록에서 `ended` 제외, `unclassified_count` 집계
10. `last_seen_at` 24시간 초과 `idle` → `ended` 간주
11. `ended`+할일없음+7일 → 삭제, 할일 있으면 유지
12. 훅 진입점이 깨진 JSON·알 수 없는 이벤트를 받아도 `exit 0` 무출력
13. scope-guard 어댑터가 기존 `<scope-guard>` 블록 형식으로 렌더

훅은 `dash_hook.py`를 서브프로세스로 실행해 종료 코드와 stdout을 확인한다. 브라우저 화면은 수동 확인한다.

## 의도적 단순화

- 폴링 2초. SSE가 더 즉각적이지만 `http.server`에서 연결을 붙잡으면 스레드를 점유하고 끊김 감지가 지저분해진다.
- 세션 분류 이력을 남기지 않는다. 현재 분류만 저장한다.
- 도구 호출 단위 진행 상황을 추적하지 않는다.
- 세션 리밋·비정상 종료를 구분하지 않는다. ④의 주제다.
- 분류 정확도를 측정하지 않는다. 틀리면 사용자가 고친다.
