# ④ 자율 실행 — 확정 스펙

작성일: 2026-07-30 · 상태: 결정 확정 (미구현)
선행: `2026-07-30-session-mapping-spec.md`(②), `2026-07-30-decision-queue-spec.md`(③)

②③에서 올라서는 것 — 세션 식별은 훅 stdin `session_id`(②D1), 자율 잡은 새 세션 id 를 받으므로 `--inherit` 로 부모·워크스페이스를 명시 상속(②D3), 판단이 막히면 `dash.py ask --on-timeout block`(③D3).

## (a) 해결하려는 문제

1. **다음 일을 스스로 집는 주체가 없음.** `/goal` + Stop 훅으로 하나의 목표를 붙잡는 것까지는 되지만, 목표가 끝나면 세션은 멈춰 서 있음. 대시보드에 착수 순서대로 정렬된 할일이 있는데 그것을 집어 시작하는 것은 사람이 해야 함.
2. **자리를 비운 시간이 비어 있음.** 리밋 재개(`~/.claude/scripts/resume-limited-jobs.py`, 5분 크론)는 이미 있지만, 그건 **멈춘 잡을 다시 미는 것**이고 새 일을 시작하지는 않음.
3. **어디까지 스스로 해도 되는지가 안 적혀 있음.** 세션마다 다르게 판단함. 커밋해도 되는지, 외부에 보내도 되는지가 그때그때 정해짐.
4. **멈춰야 할 조건이 없음.** 실패한 할일을 무한 재시도하거나 사용량을 다 태울 수 있음.

## (b) 확정한 결정

### D1. 실행 단위 = 할일 1건, 선택 규칙은 `dash.py next` 재사용

새 우선순위 로직을 만들지 않음. `app/services/planning.py` 가 뽑는 그 한 건을 그대로 씀. 근거 — ①에서 "워크스페이스 순위 + 할일 착수 순서"로 우선순위를 이미 정의했고, 자율 실행이 다른 기준으로 고르면 사람이 보는 순서와 어긋남.

동시 실행은 **1건**. 근거 — 사용량 창을 두 잡이 나눠 쓰면 둘 다 리밋에 걸리고, 같은 레포를 동시에 고치면 diff 가 섞임. `resume-limited-jobs.py` 도 같은 이유로 `MAX_PER_RUN = 1` 임.

### D2. 트리거는 기존 5분 크론에 한 줄 추가. 데몬 안 만듦

```cron
*/5 * * * * /usr/bin/python3 /home/ujung/work/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

근거 — 이미 5분 크론(`resume-limited-jobs.py`)이 돌고 잡을 띄우고 있음. 두 번째 상시 프로세스는 관리·감시 비용만 늘림. tick 은 판정만 하고 조건이 안 맞으면 아무것도 안 하고 끝남.

### D3. 실행 방식은 `claude --bg` 잡

```bash
claude --bg --model <상수> --permission-mode acceptEdits <프롬프트>
```

근거 — 포그라운드 터미널을 점유하지 않고, `~/.claude/jobs/<id>/state.json` 이 생겨 **리밋 재개를 `resume-limited-jobs.py` 가 그대로 담당**함. ④는 리밋 처리를 다시 구현하지 않음.

- 프롬프트는 `dash.py autorun-prompt <todo-id>` 가 만듦 — 워크스페이스 배경·목적·목표 + 할일 제목·컨텍스트 노트 + 아래 D4 권한 규칙 + ③ 큐 사용법
- 잡이 새로 만든 세션 id 는 런처가 읽어 `dash.py classify <child> --inherit <parent>` 로 워크스페이스에 붙임(②D3 명시 경로). 부모가 없는 경우(크론이 띄운 첫 잡) 워크스페이스를 직접 지정
- `autorun_runs` 에 `todo_id`·`claude_session_id`·`job_id` 를 기록

### D4. 실행 권한

| 행위 | 자율 세션 | 근거 |
| --- | --- | --- |
| 파일 읽기·검색 | 허용 | |
| 테스트·린트 실행 | 허용 | 검증 없는 변경은 미완성 |
| 레포 워킹트리의 코드·문서 수정 | 허용 | ④의 목적 |
| `git add` / `commit` | **금지** | 자율 세션이 만든 커밋을 사람이 되돌리는 비용 > 워킹트리 diff 를 아침에 한 번 읽는 비용 |
| `git push` / PR / 브랜치 삭제 | **금지** | 되돌릴 수 없고 밖으로 나감 |
| 외부 전송 (Jira 댓글, Confluence, 메일, 슬랙) | **금지** | 사람 이름으로 나가는 발신 |
| 삭제·이동성 명령 (`rm`, `mv`, DB `DELETE`/`UPDATE`, 마이그레이션) | **금지** | |
| 운영 서버 접속·배포 | **금지** | |
| 새 의존성 설치 | **금지** | 이 레포는 외부 의존성 0 이 규칙 |
| `~/.claude/` 하위 수정 | **금지** | headless 세션은 sensitive path 로 차단됨 — 시도해도 실패함 |
| 판단이 필요한 지점 | ③ 큐 등록 (`--on-timeout block`) | ③D3 |

**한계를 명시함** — 위 금지 목록은 프롬프트 규칙이며 기술적 차단 장치가 아님. `PreToolUse` 훅으로 강제하는 것이 맞지만 1차 범위에서 뺌(대상 명령 패턴을 다 적기 전에 만들면 오차단이 더 위험함). 대신 **커밋·푸시 금지가 안전망 역할**을 함 — 규칙을 넘어선 변경도 워킹트리에 남으므로 `git diff` 로 전부 보이고 `git checkout` 으로 되돌아감.

추가 안전망 — tick 은 대상 워크스페이스의 워킹트리가 **깨끗할 때만** 시작함(`git status --porcelain` 이 비어 있음). 사람의 미완성 변경 위에 자율 세션이 겹치면 두 변경을 분리할 수 없음.

### D5. 시작 금지·중단 조건

| 조건 | 확인 방법 | 동작 |
| --- | --- | --- |
| autorun 이 꺼져 있음 | `autorun_state.enabled` | 시작 안 함 (기본 상태) |
| 이미 자율 잡이 돌고 있음 | `autorun_runs` 에 `ended_at IS NULL` | 시작 안 함 (동시 1건) |
| 5시간 창 사용률 ≥ 90% | `app/services/usage.py` (`RATE_LIMITS_PATH`), `USAGE_CRITICAL_PCT` | 시작 안 함. 다음 tick 재확인 |
| 사용률 데이터가 아예 없음 | 사이드카에 `five_hour.used_percentage` 가 없음 | 시작 안 함 — 모르면 안 돎. 낡은 값은 그대로 쓴다(statusline 이 안 그려지면 늘 낡으므로) |
| 대상 워크스페이스 워킹트리가 더러움 | `git status --porcelain` | 그 할일 건너뛰고 다음 후보 |
| 사람이 그 잡에 프롬프트를 넣음 | `UserPromptSubmit` 훅 + 그 세션이 자율 세션 | autorun 즉시 off. 그 잡은 사람 것으로 인계 |
| 같은 할일이 2회 연속 실패 | `autorun_runs.outcome` | 그 할일 `blocked` 처리, 다음 할일로 |
| `blocked` 가 연속 3건 | `autorun_state.blocked_streak` | autorun off + 대시보드 경고 |
| ③ 큐에서 `blocked` 만료 | `decisions.status` | 그 할일을 `blocked` 로 두고 다음 할일로 |
| `next` 가 뽑을 할일 없음 | `planning.next` | 시작 안 함. 다음 tick 재확인 — 끄지 않음 |
| 리밋으로 잡이 멈춤 | `~/.claude/jobs/*/state.json` | ④는 개입 안 함. `resume-limited-jobs.py` 가 재개 |

할일의 `blocked` — ①의 상태는 `todo`/`doing`/`done` 3개임. 여기서 4번째 값을 추가하지 않고 **`autorun_runs.outcome='blocked'` 로만 기록**함. 할일 상태는 `doing` 에 머무르고 대시보드에서 "자율 실행이 막힘" 배지로 보임. 근거 — ①의 상태 집합을 늘리면 웹 UI·CLI·정렬 규칙이 다 따라 움직여야 함.

### D6. 상태 저장

```sql
autorun_state(                 -- 단일 행
  id INTEGER PRIMARY KEY CHECK (id = 1),
  enabled INTEGER NOT NULL DEFAULT 0,
  blocked_streak INTEGER NOT NULL DEFAULT 0,
  last_tick_at TEXT,
  last_tick_reason TEXT,       -- 마지막 tick 의 판정 사유. 켜져 있는데 안 도는 이유를 화면에 보임
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
- 자율 커밋·푸시·PR (D4)
- 리밋 재개 재구현 — `resume-limited-jobs.py` 가 담당. ④는 잡을 띄우는 것까지
- `PreToolUse` 강제 차단 — 1차 제외 (D4 한계)
- 워크트리 격리 — 회사 레포에 워크트리를 자동 생성하는 부작용이 큼. 대신 "워킹트리가 깨끗할 때만 시작"으로 대체
- 자율 세션이 워크스페이스·할일을 새로 만드는 것 — 있는 것만 소화함. 새 일을 스스로 정의하지 않음
- 실행 시간창 제한(밤·주말 금지) — 자리를 비운 시간에 도는 것이 목적이므로 시간으로 막지 않음. 사용률로만 막음
- 성공률 학습·모델 자동 선택 — 모델은 상수
- 도구 호출 단위 감사 로그 — 잡 전사(`~/.claude/jobs/<id>`)가 이미 남음
- 실패 원인 자동 분석·재시도 전략 — 2회 실패면 막고 넘어감

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

**건드리지 않음** — `~/.claude/scripts/resume-limited-jobs.py`, `app/services/planning.py`(호출만), `app/services/usage.py`(읽기만), `~/.claude/skills/scope-guard/*`, `categories`·`workspaces`·`todos`·`subtasks` 스키마, `TODO_STATUSES` 상수.

**착수 순서** — ②D2·D3 → ③ `ask --on-timeout block` → ④. ③ 없이 ④를 켜면 막힌 자율 세션이 갈 곳이 없음.

## 검증

`python3 -m tests` 에 `tests/test_autorun.py` 합류. tick 판정은 전부 단위 테스트로 — 실제 `claude --bg` 를 띄우지 않음(런처는 주입 가능한 함수로 분리).

1. autorun off → tick 이 아무것도 안 함
2. 실행 중 잡 존재 → 시작 안 함
3. 사용률 90% 이상 / 데이터 낡음 → 각각 시작 안 함
4. 워킹트리 더러움 → 그 할일 건너뛰고 다음 후보
5. 같은 할일 2회 실패 기록 → `blocked` 로 기록하고 다음 할일 선택
6. `blocked` 연속 3건 → autorun off, 경고 플래그
7. `next` 가 없음 → 시작만 안 하고 autorun 은 켜진 채. 판정 사유가 `last_tick_reason` 에 남음
8. 자율 세션에 `UserPromptSubmit` → autorun off
9. `autorun-tick --dry-run` 이 실행하지 않고 판정 사유만 출력
10. 실행 기록의 `outcome` 전이 (`done`/`failed`/`blocked`)

수동 확인 — `--dry-run` 으로 판정 사유를 먼저 보고, 그다음 워크스페이스 3의 안전한 할일 1건으로 실제 잡을 한 번 띄워 diff·잡 로그를 검토.
