# ④ 자율 실행 — 확정 스펙

작성일: 2026-07-30 · 개정: 2026-08-03 · 상태: 결정 확정 (미구현)
선행: `2026-07-30-session-mapping-spec.md`(②), `2026-08-03-waiting-status-spec.md`(⑥), `2026-07-30-decision-queue-spec.md`(③)

②③⑥에서 올라서는 것 — 세션 식별은 훅 stdin `session_id`(②D1), 자율 잡은 새 세션 id 를 받으므로 부모·워크스페이스를 명시 상속(②D3), 판단이 막히면 `dash.py ask --on-timeout block`(③D3), 착수 가능 여부는 할일 상태 `waiting`/`todo` 가 정함(⑥D1).

**2026-08-03 개정 요약** — 7/30 이후 master 에 들어온 것과 사용자 결정을 반영함.

| 항목 | 무엇이 바뀌었나 |
| --- | --- |
| 선제조건 게이트 | 자율 실행은 조건이 충족된 할일에서만 시작함. `waiting` 은 후보에서 제외 (D1·D5, 정본은 ⑥) |
| 할일 상태 4번째 값 | "①의 상태 집합을 늘리지 않음" 결정을 뒤집음. `waiting` 을 추가함 (⑥D1). `autorun_runs.outcome='blocked'` 는 실행 기록으로만 남음 |
| ②의 미구현 | master 에 `CLAUDE_CODE_SESSION_ID` 참조가 없고 `classify --inherit` 도 없음. ② 없이 ④를 붙이려면 런처가 워크스페이스를 직접 지정해야 함 (D3) |
| `--bg` 하네스 기본 지시 | 백그라운드 잡에는 "워크트리로 격리하고, 끝나면 커밋·푸시·draft PR" 이 시스템 프롬프트로 들어감. D4 와 정반대라 프롬프트가 명시적으로 무효화해야 함 (D3·D4) |
| 워크트리 가드 훅 | `hooks/worktree_guard.py` 가 메인 체크아웃 소스 편집을 차단함(현재 플래그 파일이 없어 비활성). 켜지면 자율 세션은 코드를 못 고침 (D4) |
| 상태 변경 권한 | D4 의 "DB UPDATE 금지" 와 D8 의 `set-status` 요구가 모순이었음. `dash.py` 경유는 허용, 직접 sqlite 조작은 금지로 정리 (D4) |

## (a) 해결하려는 문제

1. **다음 일을 스스로 집는 주체가 없음.** `/goal` + Stop 훅으로 하나의 목표를 붙잡는 것까지는 되지만, 목표가 끝나면 세션은 멈춰 서 있음. 대시보드에 착수 순서대로 정렬된 할일이 있는데 그것을 집어 시작하는 것은 사람이 해야 함.
2. **자리를 비운 시간이 비어 있음.** 리밋 재개(`~/.claude/scripts/resume-limited-jobs.py`, 5분 크론)는 이미 있지만, 그건 **멈춘 잡을 다시 미는 것**이고 새 일을 시작하지는 않음.
3. **어디까지 스스로 해도 되는지가 안 적혀 있음.** 세션마다 다르게 판단함. 커밋해도 되는지, 외부에 보내도 되는지가 그때그때 정해짐.
4. **멈춰야 할 조건이 없음.** 실패한 할일을 무한 재시도하거나 사용량을 다 태울 수 있음.

## (b) 확정한 결정

### D1. 실행 단위 = 할일 1건, 선택 규칙은 `dash.py next` 재사용

새 우선순위 로직을 만들지 않음. `app/services/planning.py` 가 뽑는 그 한 건을 그대로 씀. 근거 — ①에서 "워크스페이스 순위 + 할일 착수 순서"로 우선순위를 이미 정의했고, 자율 실행이 다른 기준으로 고르면 사람이 보는 순서와 어긋남.

**선제조건이 충족된 할일에서만 시작함.** ⑥D3 이 `waiting` 을 `next` 후보에서 빼므로 tick 은 별도 필터를 두지 않고 `planning.next_todo` 를 그대로 부름 — 대기 판정을 두 곳에서 하지 않는다. tick 은 세션 id 없이 호출하므로(`claude_session_id=None`) 다른 활성 세션이 이미 잡은 할일도 함께 빠짐.

조건 문장이 붙은 채 `todo` 인 할일은 "사람이 조건을 풀었다"는 뜻이지만, 판정이 낡았을 수 있음. 그래서 조건 전문을 프롬프트에 싣고 **자율 세션의 첫 단계를 조건 재확인으로** 둠. 미충족이라고 판단하면 코드를 건드리기 전에 `dash.py set-status todo <id> waiting` 으로 되돌리고 종료함 — 그 실행은 `outcome='blocked'` 로 기록되고 다음 tick 이 다음 후보를 집음. 조건 판정은 자연어라 코드가 못 하므로 이 재확인은 프롬프트 규칙이다.

동시 실행은 **1건**. 근거 — 사용량 창을 두 잡이 나눠 쓰면 둘 다 리밋에 걸리고, 같은 레포를 동시에 고치면 diff 가 섞임. `resume-limited-jobs.py` 도 같은 이유로 `MAX_PER_RUN = 1` 임.

### D2. 트리거는 기존 5분 크론에 한 줄 추가. 데몬 안 만듦

```cron
*/5 * * * * /usr/bin/python3 /home/ujung/work/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

근거 — 이미 5분 크론(`resume-limited-jobs.py`)이 돌고 잡을 띄우고 있음. 두 번째 상시 프로세스는 관리·감시 비용만 늘림. tick 은 판정만 하고 조건이 안 맞으면 아무것도 안 하고 끝남.

### D3. 실행 방식은 `claude --bg` 잡

```
claude --bg --model <상수> --permission-mode acceptEdits <프롬프트>
```

근거 — 포그라운드 터미널을 점유하지 않고, `~/.claude/jobs/<id>/state.json` 이 생겨 **리밋 재개를 `resume-limited-jobs.py` 가 그대로 담당**함. ④는 리밋 처리를 다시 구현하지 않음.

- 프롬프트는 `dash.py autorun-prompt <todo-id>` 가 만듦 — 워크스페이스 배경·목적·목표 + 할일 제목·컨텍스트 노트 + **선제조건 전문과 재확인 지시**(D1) + 아래 D4 권한 규칙 + ③ 큐 사용법
- 잡이 새로 만든 세션 id 는 런처가 `~/.claude/jobs/<job-id>/state.json` 의 `sessionId` 로 읽어 워크스페이스에 붙임. ②D3 의 `classify --inherit` 는 master 에 아직 없으므로, ② 구현 전에는 크론이 띄운 잡이 부모가 없는 경우와 동일하게 **워크스페이스를 직접 지정**함
- `autorun_runs` 에 `todo_id`·`claude_session_id`·`job_id` 를 기록
- **하네스 기본 지시를 프롬프트가 무효화함.** `--bg` 로 띄운 세션에는 "코드 변경 전 워크트리로 격리하라", "끝나면 커밋·푸시하고 draft PR 을 올려라"가 시스템 프롬프트로 들어옴 — D4 와 정반대다. `autorun-prompt` 는 이 두 항목을 지목해 취소하는 문장을 넣음(워크트리를 만들지 않고 지정된 워킹트리에서 작업한다, 커밋·푸시·PR 을 하지 않고 변경을 워킹트리에 남긴 채 끝낸다). 프롬프트로 프롬프트를 이기는 구조이므로 D4 의 "기술적 차단이 아님" 한계가 실제로 더 얇음 — 첫 실전 잡에서 이 두 항목이 지켜지는지를 수동 확인 항목으로 둠

### D4. 실행 권한

| 행위 | 자율 세션 | 근거 |
| --- | --- | --- |
| 파일 읽기·검색 | 허용 | |
| 테스트·린트 실행 | 허용 | 검증 없는 변경은 미완성 |
| 레포 워킹트리의 코드·문서 수정 | 허용 | ④의 목적 |
| `git add` / `commit` | **금지** | 자율 세션이 만든 커밋을 사람이 되돌리는 비용 > 워킹트리 diff 를 아침에 한 번 읽는 비용 |
| `git push` / PR / 브랜치 삭제 | **금지** | 되돌릴 수 없고 밖으로 나감 |
| 외부 전송 (Jira 댓글, Confluence, 메일, 슬랙) | **금지** | 사람 이름으로 나가는 발신 |
| `dash.py set-status`·`add-todo`·`link-todo`·`ask` | 허용 | 대시보드에 진행 상태를 남기는 것이 ④의 일부(D8). 대기 되돌리기(⑥D2)도 이 경로 |
| 삭제·이동성 명령 (`rm`, `mv`, sqlite 직접 `DELETE`/`UPDATE`, 마이그레이션) | **금지** | 상태 변경은 위의 `dash.py` 명령으로만. DB 를 직접 열어 고치면 검증을 우회함 |
| 운영 서버 접속·배포 | **금지** | |
| 새 의존성 설치 | **금지** | 이 레포는 외부 의존성 0 이 규칙 |
| `~/.claude/` 하위 수정 | **금지** | headless 세션은 sensitive path 로 차단됨 — 시도해도 실패함 |
| 판단이 필요한 지점 | ③ 큐 등록 (`--on-timeout block`) | ③D3 |

**한계를 명시함** — 위 금지 목록은 프롬프트 규칙이며 기술적 차단 장치가 아님. `PreToolUse` 훅으로 강제하는 것이 맞지만 1차 범위에서 뺌(대상 명령 패턴을 다 적기 전에 만들면 오차단이 더 위험함). 대신 **커밋·푸시 금지가 안전망 역할**을 함 — 규칙을 넘어선 변경도 워킹트리에 남으므로 `git diff` 로 전부 보이고 `git checkout` 으로 되돌아감.

추가 안전망 — tick 은 대상 워크스페이스의 워킹트리가 **깨끗할 때만** 시작함(`git status --porcelain` 이 비어 있음). 사람의 미완성 변경 위에 자율 세션이 겹치면 두 변경을 분리할 수 없음.

**워크트리 가드 훅과의 관계** — master 에 `hooks/worktree_guard.py` 가 들어왔음. `~/work/` 아래 레포의 **메인 체크아웃에서 소스 편집을 차단**하는 PreToolUse 훅이고(`.md`·`docs/`·설정 파일은 통과), `~/.claude/worktree-guard.on` 플래그 파일이 있을 때만 동작함. 지금은 그 파일이 없어 비활성이므로 D4 의 "메인 워킹트리에서 작업" 과 충돌하지 않음. 이 플래그를 켜면 자율 세션은 코드를 한 줄도 못 고침 — 그때는 둘 중 하나를 골라야 하고, 이 스펙은 **후자를 택하지 않음**을 기본으로 둠.

| 선택 | 대가 |
| --- | --- |
| 자율 잡을 `ALLOW_MAIN_CHECKOUT=1` 로 띄움 | 가드를 무력화하므로 "사람 변경과 안 겹친다"는 보장이 워킹트리 청결 검사 하나로 줄어듦 |
| 자율 세션도 워크트리를 쓰게 함 | (c) 의 "워크트리 격리 안 함" 을 뒤집는 결정. `hooks/worktree_serve.py`(Stop)가 웹 프로젝트 워크트리에 서버가 없으면 종료를 막으므로 자율 잡이 끝나지 못하는 문제가 따라옴 |

### D5. 시작 금지·중단 조건

| 조건 | 확인 방법 | 동작 |
| --- | --- | --- |
| autorun 이 꺼져 있음 | `autorun_state.enabled` | 시작 안 함 (기본 상태) |
| 이미 자율 잡이 돌고 있음 | `autorun_runs` 에 `ended_at IS NULL` | 시작 안 함 (동시 1건) |
| 5시간 창 사용률 ≥ 90% | `app/services/usage.py` (`RATE_LIMITS_PATH`), `USAGE_CRITICAL_PCT` | 시작 안 함. 다음 tick 재확인 |
| 사용률 데이터가 15분 넘게 낡음 | `USAGE_STALE_SECONDS` | 시작 안 함 — 모르면 안 돎 |
| 후보 할일이 `waiting` | `planning.next_todo` 가 이미 제외 (⑥D3) | 그 할일은 애초에 후보로 오지 않음 |
| 뽑힌 할일에 조건 문장이 있음 | `todos.precondition` | 조건 전문을 프롬프트에 싣고, 자율 세션이 첫 단계로 재확인. 미충족이면 `waiting` 으로 되돌리고 `outcome='blocked'` 로 종료 (D1) |
| `next` 가 뽑을 게 없는데 `waiting` 만 남음 | `planning.next_todo` 가 None | autorun off. 사람이 조건을 풀어야 다시 켜짐 |
| 대상 워크스페이스 워킹트리가 더러움 | `git status --porcelain` | 그 할일 건너뛰고 다음 후보 |
| 사람이 그 잡에 프롬프트를 넣음 | `UserPromptSubmit` 훅 + 그 세션이 자율 세션 | autorun 즉시 off. 그 잡은 사람 것으로 인계 |
| 같은 할일이 2회 연속 실패 | `autorun_runs.outcome` | 그 할일 `blocked` 처리, 다음 할일로 |
| `blocked` 가 연속 3건 | `autorun_state.blocked_streak` | autorun off + 대시보드 경고 |
| ③ 큐에서 `blocked` 만료 | `decisions.status` | 그 할일을 `blocked` 로 두고 다음 할일로 |
| `next` 가 뽑을 할일 없음 | `planning.next` | autorun off |
| 리밋으로 잡이 멈춤 | `~/.claude/jobs/*/state.json` | ④는 개입 안 함. `resume-limited-jobs.py` 가 재개 |

할일의 `blocked` — **7/30 결정을 뒤집었음.** 원래는 ①의 3상태를 지키려고 `autorun_runs.outcome='blocked'` 로만 기록하기로 했으나, 대기를 보드에서 구분해 보는 것이 목적이 되어 ⑥에서 상태 값 `waiting` 을 추가함. 두 값의 역할은 아래로 나눔.

| 값 | 뜻 | 어디서 보이나 |
| --- | --- | --- |
| `todos.status='waiting'` (⑥) | 선제조건이 안 풀려 **지금 착수할 수 없음**. 사람·세션이 명시적으로 전환 | 보드 카드(딤 + 조건 한 줄), `next` 후보 제외 |
| `autorun_runs.outcome='blocked'` (④) | **그 실행이** 막혀 끝났음(조건 미충족, ③ 큐 `blocked` 만료, 2회 연속 실패) | 보드 "자율 실행이 막힘" 배지, 실행 이력 |

조건 미충족으로 막힌 경우 두 값이 함께 남음 — 할일은 `waiting` 으로 내려가고 그 실행은 `blocked` 로 기록됨. 그 외 사유(큐 만료·연속 실패)로 막힌 경우 할일 상태는 `doing` 에 머무름 — 조건이 아니라 실행이 실패한 것이므로 대기로 내리면 원인이 뒤바뀜.

### D6. 상태 저장

```sql
autorun_state(                 -- 단일 행
  id INTEGER PRIMARY KEY CHECK (id = 1),
  enabled INTEGER NOT NULL DEFAULT 0,
  blocked_streak INTEGER NOT NULL DEFAULT 0,
  last_tick_at TEXT,
  updated_at TEXT NOT NULL);

autorun_runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  todo_id INTEGER NOT NULL REFERENCES todos(id),
  claude_session_id TEXT,      -- --bg 가 만든 세션 id. 런처가 읽어 기록
  job_id TEXT,                 -- ~/.claude/jobs/<id>
  started_at TEXT NOT NULL,
  ended_at TEXT,
  outcome TEXT);               -- done | failed | blocked
```

날짜는 ISO8601 UTC (①과 동일). 단일 행 테이블을 씀 — 키-값 설정 테이블을 새로 만드는 것보다 필드 셋뿐인 행 하나가 짧음.

### D7. 켜고 끄기는 명시적, 기본은 off

`dash.py autorun on|off|status` + 웹 UI 토글. 기본 off. 근거 — 기본 on 은 사고임. 자동으로 다시 켜지는 경로를 만들지 않음(D5 로 꺼진 뒤 사람이 다시 켬).

### D8. 완료 처리는 자율 세션이 직접

끝내면 `dash.py set-status todo <id> done` + `--note` 로 결과 요약을 할일 컨텍스트에 남김. 사람은 아침에 대시보드에서 무엇이 done 으로 넘어갔는지와 `git diff` 를 봄.

## (c) 의도적으로 안 하는 것

- 여러 할일 동시 실행 (D1)
- 자율 커밋·푸시·PR (D4). `--bg` 하네스가 그렇게 하라고 지시하더라도 프롬프트가 취소함 (D3)
- 선제조건 충족 여부의 자동 판정 — 자연어 조건이라 코드가 못 함. tick 은 상태(`waiting`)만 보고, 문장 판단은 자율 세션이 프롬프트 규칙으로 함 (D1, ⑥D2)
- 조건이 풀리기를 기다려 자동으로 `waiting` → `todo` 로 올리는 것 — 올리는 것은 사람의 판단 (⑥D2)
- 리밋 재개 재구현 — `resume-limited-jobs.py` 가 담당. ④는 잡을 띄우는 것까지
- `PreToolUse` 강제 차단 — 1차 제외 (D4 한계)
- 워크트리 격리 — 회사 레포에 워크트리를 자동 생성하는 부작용이 큼. 대신 "워킹트리가 깨끗할 때만 시작"으로 대체
- 자율 세션이 워크스페이스·할일을 새로 만드는 것 — 있는 것만 소화함. 새 일을 스스로 정의하지 않음
- 실행 시간창 제한(밤·주말 금지) — 자리를 비운 시간에 도는 것이 목적이므로 시간으로 막지 않음. 사용률로만 막음
- 성공률 학습·모델 자동 선택 — 모델은 상수
- 도구 호출 단위 감사 로그 — 잡 전사(`~/.claude/jobs/<id>`)가 이미 남음
- 실패 원인 자동 분석·재시도 전략 — 2회 실패면 막고 넘어감
- `usage.snapshot()` 을 판정에 쓰는 것 — 그 함수는 조회하면서 `usage_samples` 에 한 줄 적립하므로 tick 이 5분마다 부르면 추이 그래프에 tick 이 섞임. 사이드카(`RATE_LIMITS_PATH`)를 읽어 % 만 보는 경로를 씀. 계정이 둘이면 5시간 창도 둘이지만 사이드카에는 지금 로그인한 계정 것만 있음 — 그 기준으로 판정함

## (d) 구현 시 건드릴 파일 경계

| 파일 | 변경 |
| --- | --- |
| `app/db.py` | `autorun_state`, `autorun_runs` 추가 |
| `app/repositories/autorun.py` | 신규 — 상태 읽기·쓰기, 실행 기록 |
| `app/services/autorun.py` | 신규 — tick 판정(D5 표), 프롬프트 조립, 잡 실행·세션 id 회수 |
| `dash.py` | `autorun on/off/status`, `autorun-tick [--dry-run]`, `autorun-prompt <todo-id>` |
| `hooks/dash_hook.py` | `UserPromptSubmit` 에서 그 세션이 자율 세션이면 autorun off |
| `server.py` | `POST /api/autorun` (토글), `GET /api/sessions` 응답에 autorun 상태·최근 실행 추가 |
| `static/js/autorun.js`, `static/index.html`, `static/css/app.css` | 토글·상태·막힘 배지 |
| `app/constants.py` | `AUTORUN_MODEL`, `AUTORUN_MAX_CONCURRENT=1`, `AUTORUN_FAIL_LIMIT=2`, `AUTORUN_BLOCKED_STREAK_LIMIT=3`, `AUTORUN_OUTCOMES` |
| `tests/test_autorun.py` | 신규 |
| crontab | tick 한 줄 추가 |

**건드리지 않음** — `~/.claude/scripts/resume-limited-jobs.py`, `app/services/planning.py`(호출만 — 후보 조건은 ⑥가 고침), `app/services/usage.py`(사이드카 읽기만), `hooks/worktree_guard.py`·`hooks/worktree_serve.py`, `~/.claude/skills/scope-guard/*`, `categories`·`workspaces`·`todos`·`subtasks` 스키마, `TODO_STATUSES` 상수(⑥가 고침).

**착수 순서** — ②D2·D3 → ⑥(`waiting` 상태) → ③ `ask --on-timeout block` → ④.

| 선행 | 없으면 무슨 일이 나나 |
| --- | --- |
| ② | 런처가 자율 잡의 세션을 워크스페이스에 붙이는 경로가 임시로 두 곳에 생김. ④는 워크스페이스 직접 지정으로 우회할 수 있으나 ② 구현 때 다시 뜯김 |
| ⑥ | tick 이 조건 미충족 할일을 집고, 자율 세션이 "조건이 안 풀렸다"를 남길 자리가 없음 |
| ③ | 막힌 자율 세션이 갈 곳이 없음 |

## 검증

`python3 -m tests` 에 `tests/test_autorun.py` 합류. tick 판정은 전부 단위 테스트로 — 실제 `claude --bg` 를 띄우지 않음(런처는 주입 가능한 함수로 분리).

1. autorun off → tick 이 아무것도 안 함
2. 실행 중 잡 존재 → 시작 안 함
3. 사용률 90% 이상 / 데이터 낡음 → 각각 시작 안 함
4. 워킹트리 더러움 → 그 할일 건너뛰고 다음 후보
5. 같은 할일 2회 실패 기록 → `blocked` 로 기록하고 다음 할일 선택
6. `blocked` 연속 3건 → autorun off, 경고 플래그
7. `next` 가 없음 → autorun off
8. 자율 세션에 `UserPromptSubmit` → autorun off
9. `autorun-tick --dry-run` 이 실행하지 않고 판정 사유만 출력
10. 실행 기록의 `outcome` 전이 (`done`/`failed`/`blocked`)
11. `waiting` 할일만 남은 상태에서 tick → 시작하지 않고 autorun off
12. `autorun-prompt` 출력에 조건 전문·재확인 지시·커밋 금지·워크트리 금지 문장이 모두 들어감 (문자열 검사)
13. 조건 미충족으로 세션이 `set-status waiting` 한 뒤의 실행 기록이 `outcome='blocked'` 이고 할일은 `waiting`

수동 확인 — `--dry-run` 으로 판정 사유를 먼저 보고, 그다음 워크스페이스 3의 안전한 할일 1건으로 실제 잡을 한 번 띄워 아래를 확인한다.

| 확인할 것 | 왜 |
| --- | --- |
| 워크트리를 만들지 않고 지정된 워킹트리에서 작업했는지 | `--bg` 하네스 기본 지시를 프롬프트가 이겼는지 (D3) |
| 커밋·푸시·PR 이 없고 변경이 워킹트리에 남았는지 | 같음. D4 의 안전망이 성립하는 근거 |
| 조건이 붙은 할일이면 첫 단계에서 조건을 재확인했는지 | D1 |
| `git diff` 와 잡 전사(`~/.claude/jobs/<id>`) | 규칙을 넘어선 변경이 없는지 |
