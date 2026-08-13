# ② 세션 매핑 — 확정 스펙

작성일: 2026-07-30 · 상태: 결정 확정 (일부 미구현) · 선행: `2026-07-29-session-link-design.md`
후속: `2026-07-30-decision-queue-spec.md`(③), `2026-07-30-autorun-spec.md`(④)

07-29 설계 문서를 대체하지 않음. 그 문서가 남긴 미확정 항목(세션 식별 방식 확정, scope-guard 흡수 범위, 자식 세션 처리)을 결정으로 못박는 델타 문서임. 충돌 시 이 문서가 우선.

## 07-29 설계 대비 현재 상태

| 항목 | 07-29 설계 | 2026-07-30 실제 | 남은 일 |
| --- | --- | --- | --- |
| sessions·session_todos 테이블 | 추가 | 적용 | 없음 |
| dash_hook.py 4개 이벤트 | 등록 예정 | `settings.json` 에 4건 등록됨 (`<메인 체크아웃>/hooks/dash_hook.py`) | 없음 |
| 컨텍스트 주입 (분류/분류 전) | 설계 | 동작 중 | 없음 |
| scope-guard `scope_db.py` → dash.db 어댑터 | 교체 | 교체됨 (`scope_db.py.bak` 보존) | 없음 |
| scope-guard `session-inject.sh` 훅 제거 | 제거 | `settings.json` 에 없음 | 없음 |
| `scope.db` | 백업만 | `scope.db.bak` 존재, 마이그레이션 안 함 | 없음 |
| README ② 서술 | — | "훅 등록 아직 안 함", "scope-guard 흡수 미적용" — 둘 다 사실과 다름 | 정정 |
| 세션 식별 방식 확정 | 문장으로만 | 결정 D1·D2 로 확정 | D2 미구현 |
| fork·자식 세션 | 없음 | 새 세션으로 등록돼 분류 전으로 다시 셈 | 결정 D3 구현 |

README 는 낡은 상태임. 이 문서 작성과 함께 정정함.

## (a) 해결하려는 문제

1. **세션 식별 방식이 문서에 후보 비교로 남아 있지 않음.** tmux 방식을 쓸 수 없다는 것만 구두로 전해져 세션마다 다시 판단됨.
2. **CLI 가 자기 세션을 모름.** `dash.py classify <session>` 이 36자 UUID 를 인자로 요구해, 모델이 주입 블록에서 값을 옮겨 적어야 함. 옮겨 적기 실패·누락이 분류 누락으로 이어짐.
3. **fork·백그라운드 자식 세션이 부모와 무관한 새 세션으로 잡힘.** 같은 작업이 목록에 2줄로 뜨고 "분류 전 N건" 경고가 자식 수만큼 늘어남. ④ 자율 실행이 `claude --bg` 로 도는 구조이므로 방치하면 ④에서 그대로 터짐.
4. **scope-guard 흡수 범위가 "어디까지"인지 안 적혀 있음.** 어댑터·훅 제거는 됐지만 SKILL.md·스킬 자체의 존치 여부가 미결.

## 1. 세션 식별 방식 — 후보 비교

| 후보 | 값을 얻는 경로 | 판단 | 사유 |
| --- | --- | --- | --- |
| A. 훅 stdin `session_id` | SessionStart / UserPromptSubmit / Stop / SessionEnd 페이로드 | **확정 (권위)** | 4개 이벤트 전부에 실려옴. resume·compact 시 같은 값 유지. 이미 `dash_hook.py` 가 이 값으로 동작 중 |
| B. `CLAUDE_CODE_SESSION_ID` 환경변수 | 세션이 띄운 하위 프로세스 환경 | **확정 (CLI 폴백)** | 이 세션에서 훅 주입값 `d1d473e4-…` 와 일치 확인. 모델이 UUID 를 옮겨 적지 않아도 CLI 가 자기 세션을 앎 |
| C. `transcript_path` 파일명 | 페이로드 경로 `~/.claude/projects/<slug>/<uuid>.jsonl` | 보조 | A 와 같은 값의 사본. 전사 본문이 필요할 때(④ 실패 원인 확인)만 |
| D. `cwd` + 브랜치 추론 | git | 불가 | 같은 저장소에서 여러 세션이 동시에 돎. 1:1 식별 불가 |
| E. tmux pane id / `capture-pane` | tmux | 불가 | 아래 |

07-29 문서가 언급한 `CLAUDE_SESSION_ID` 는 이 환경에 없음. 실제 이름은 `CLAUDE_CODE_SESSION_ID` 임.

### tmux 방식이 불가한 사유

| 사유 | 확인한 근거 |
| --- | --- |
| tmux 서버 없이 세션이 돎 | `tmux -V` = 3.4 (설치돼 있음), `$TMUX` 빈 값, `tmux list-sessions` = no server. 이 문서를 쓰는 세션 자체가 pane 없이 동작 |
| pane 이 아예 없는 진입점이 존재 | `claude --bg` 백그라운드 잡, `claude -p`, 크론(`resume-limited-jobs.py`), 데스크톱·IDE 진입점. 이 세션은 `CLAUDE_CODE_ENTRYPOINT=cli`, `CLAUDE_JOB_DIR=~/.claude/jobs/d1d473e4` |
| `capture-pane` 은 렌더된 화면 텍스트 | 화면에 session UUID 가 찍히지 않음. 폭·스크롤·테마에 따라 파싱이 깨짐 |
| pane 수명과 세션 수명이 다름 | resume 은 pane 이 새것인데 세션은 같음, fork 는 pane 이 같은데 세션이 다름. pane 기준 식별은 양쪽으로 어긋남 |
| ④가 pane 없는 실행을 전제 | 자율 실행은 백그라운드 잡으로 도는 것이 목적. pane 기준 식별은 ④에서 원리적으로 못 씀 |

tmux 연동은 후속으로도 두지 않음. 영구 배제.

## (b) 확정한 결정

### D1. 식별 권위는 훅 stdin `session_id`

`sessions.claude_session_id` 의 유일한 출처. 다른 경로로 얻은 값은 이 값과 일치할 때만 유효. (구현 완료 — 변경 없음)

### D2. CLI 는 세션 인자를 생략하면 환경변수로 자기 세션을 찾음

`dash.py` 의 `<session>` 위치 인자를 선택으로 바꿈. 생략 시 `os.environ["CLAUDE_CODE_SESSION_ID"]` 를 씀. 값이 없거나 DB 에 그 세션이 없으면 기존과 같이 에러.

- 대상: `classify`, `link-todo`, `show-todo --session`, ③의 `ask`·`answer`, ④의 명령 전부
- 근거: 주입 블록의 UUID 를 매 명령에 옮겨 적는 것은 순수 비용이고 실패 지점임. 환경변수는 이 세션에서 일치 확인됨
- 한계: 사용자가 터미널에서 직접 실행하면 값이 없음 → 그때는 인자를 명시. 에러 문구에 그 사실을 적음

### D3. fork·자식 세션은 부모 분류를 상속

`SessionStart` 페이로드의 `source` 로 분기함. 이 세션에서 `SessionStart:startup` 과 `SessionStart:fork` 두 값을 관측함(훅 실행 라벨). **구현 착수 시 페이로드를 한 번 덤프해 `source` 실제 값 집합을 확인할 것** — 아래 표의 `clear` 는 미확인 추정임.

| `source` | `session_id` | 동작 |
| --- | --- | --- |
| `startup` | 새 값 | 새 행 등록, 분류 전 (현재 동작) |
| `resume` | 기존 값 유지 | 기존 행 갱신, 분류 유지 (구현됨) |
| `compact` | 기존 값 유지 | 위와 동일 |
| `clear` | 미확인 | `startup` 과 동일 취급 |
| `fork` | 새 값 | 부모 분류 상속 |

상속 규칙 — 두 경로를 둠.

| 경로 | 방법 | 정확도 |
| --- | --- | --- |
| 명시 (④·런처가 부모를 아는 경우) | `dash.py classify <child> --inherit <parent-session>` 로 부모의 category·workspace 복사 + `parent_session_id` 기록 | 정확 |
| 추정 (훅만으로 감지된 fork) | 같은 `cwd` 의 **24시간 내 가장 최근 분류된 세션**에서 상속 | 휴리스틱 |

추정 경로의 천장을 명시함 — 같은 디렉터리에서 무관한 작업을 하던 세션의 분류를 물려받을 수 있음. 24시간·최근 1건으로 제한하고, 페이로드에 부모 세션 id 필드가 생기면 그 값으로 교체함. 구현 시 `# ponytail: cwd 휴리스틱, 페이로드에 부모 id 가 생기면 교체` 주석을 남김.

표시 — 자식 세션은 목록에서 `↳` 를 붙여 부모 아래 줄로 렌더. 상속으로 분류가 채워지므로 `unclassified_count` 에서 자동으로 빠짐. 자식을 접거나 합치지 않음(무슨 잡이 도는지 보이는 것이 목적).

### D4. scope-guard 흡수는 현재 적용된 선에서 종료

| 항목 | 결정 | 근거 |
| --- | --- | --- |
| `scope_db.py` dash.db 어댑터 | 유지 | 저장소가 하나(dash.db)로 합쳐진 것이 흡수의 본질. 이미 달성 |
| `SKILL.md` · `/scope-guard` 명령 | **존치** | 입구가 둘이어도 저장소가 하나면 중복이 아님. Jira 브랜치에서 목표를 세우는 근육기억을 대체할 것이 없음 |
| `session-inject.sh` | 제거 상태 유지 (파일은 남기고 훅 등록만 없음) | 롤백 경로 보존 |
| `scope.db` 데이터 마이그레이션 | **안 함** | 유일 데이터 KT-1530 이 워크스페이스로 이미 존재. `scope.db.bak` 백업만 |
| scope-guard 를 대시보드 코드로 이관 | **안 함** | 어댑터 90줄로 끝난 것을 레포 안으로 옮길 이유 없음 |

**알려진 위험 (별건, ②에서 고치지 않음)** — `scope_db.py` 의 `set-steps` 는 워크스페이스의 할일을 전부 삭제한 뒤 재삽입함(`cmd_set_steps`). 대시보드 할일에는 하위할일과 컨텍스트 노트가 붙으므로, 워크스페이스 3처럼 할일이 쌓인 곳에서 `/scope-guard set-steps` 를 실행하면 그것들이 날아감. 고치는 방향은 "기존 할일이 있으면 거부" 한 줄이지만 ③④와 무관하므로 별도 할일로 분리함.

### D5. README 정정

②의 상태 서술("훅 등록 아직 안 함", "scope-guard 흡수 미적용")과 "아직 없는 것" 목록을 사실에 맞게 고치고 이 문서 3건을 링크함.

## (c) 의도적으로 안 하는 것

- tmux 연동 — 후속으로도 두지 않음 (위 사유표)
- 세션 분류 이력 — 현재 분류만 저장. 언제 무엇으로 바뀌었는지 안 남김
- 도구 호출 단위 진행 상황(현재 도구·파일) — 07-29 결정 승계
- 부모-자식 트리 UI — 목록에 `↳` 한 단계만. 접기·펼치기 없음
- 자식 세션의 실패를 부모 세션에 역전파 — ④의 주제
- 분류 정확도 측정 — 틀리면 사용자가 대시보드에서 고침
- 세션별 토큰·비용 귀속 — 사용량 대시보드(별건, 할일 30)의 영역

## (d) 구현 시 건드릴 파일 경계

| 파일 | 변경 |
| --- | --- |
| `app/db.py` | `sessions` 에 `parent_session_id TEXT` 추가 (ALTER, 기존 4테이블 무변경) |
| `app/repositories/sessions.py` | `register(..., source=)`, `inherit_classification(child, parent)`, `find_recent_classified(cwd, hours)`, `list_active` 에 `parent_session_id` 포함 |
| `hooks/dash_hook.py` | `_on_session_start` 에서 `payload["source"]` 분기 → fork 면 상속 시도 |
| `dash.py` | 세션 인자 생략 시 env 폴백 헬퍼 1개 추가, `classify --inherit` |
| `app/constants.py` | `SESSION_ID_ENV`, `SESSION_SOURCES`, `INHERIT_WINDOW_HOURS = 24` |
| `static/js/sessions.js` | 자식 세션 `↳` 표시 |
| `tests/test_sessions.py` | 아래 검증 항목 |
| `README.md` | ② 상태 정정 + 문서 3건 링크 |

**건드리지 않음** — `categories`·`workspaces`·`todos`·`subtasks` 테이블, `app/services/{board,planning,usage}.py`, `static/js/{board,workspace,categories,dnd}.js`, `server.py` 기존 엔드포인트, `~/.claude/skills/scope-guard/*`.

**착수 전 확인** — 이 문서를 쓰는 시점에 다른 세션이 `dash.py`·`server.py`·`app/constants.py`·`static/*` 를 커밋 전 상태로 고치고 있음(사용량 대시보드 작업). 착수 시 `git status`·`git log` 로 그 변경이 들어왔는지 먼저 확인.

## 검증

`python3 -m tests` 에 합류. 07-29 문서의 13개 항목에 더함.

1. `source=fork` + 같은 cwd 에 24시간 내 분류 세션 → 자식이 분류를 상속하고 `parent_session_id` 가 채워짐
2. `source=fork` + 상속 후보 없음 → 분류 전으로 남고 에러 없음
3. 상속 후보가 24시간을 넘음 → 상속 안 함
4. `classify --inherit <parent>` 로 명시 상속
5. 세션 인자 생략 + `CLAUDE_CODE_SESSION_ID` 설정 → 그 세션에 적용됨
6. 세션 인자 생략 + 환경변수 없음 → stderr + exit 1, 인자를 명시하라는 문구
7. `unclassified_count` 가 상속된 자식을 세지 않음
