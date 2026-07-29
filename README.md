# 작업 대시보드

카테고리 > 워크스페이스 > 할일 > 하위할일 4계층으로 작업을 관리하는 1인용 로컬 도구.
사람은 웹으로, Claude는 CLI로 같은 sqlite DB를 쓴다. 외부 의존성 0.

## 실행

```bash
python3 server.py                    # http://127.0.0.1:9080
python3 server.py --host 0.0.0.0     # 폰에서 볼 때 (인증 없음, LAN 노출 주의)
```

## CLI

```bash
python3 dash.py ls                                    # 전체 트리
python3 dash.py ls --group-by category                # 카테고리 기준
python3 dash.py next                                  # 다음에 할 일
python3 dash.py add-workspace 개발 "KT 동시성" --goal "락 재설계" --jira KT-1530
python3 dash.py add-todo "락 초안" --workspace 1
python3 dash.py add-todo "문의 회신" --category 운영    # 미분류로 들어감
python3 dash.py add-subtask 2 "k6 시나리오"
python3 dash.py move-todo 3 --workspace none          # 미분류로 내리기
python3 dash.py set-status todo 3 doing
python3 dash.py reorder workspaces 2 1                # 순위 교체
python3 dash.py show KT-1530                          # Jira ID 로도 조회
python3 dash.py done-today --json                     # daily-todo 로 넘길 입력
```

`--json` 은 Claude 가 파싱하기 위한 출력이다.

## 테스트

```bash
python3 -m tests
```

## 데이터

DB는 `~/.claude/work-dashboard/dash.db`. 환경변수 `WORK_DASHBOARD_DB` 로 바꿀 수 있다.
첫 실행 시 카테고리 6개(개발 / 운영 / 장애 대응 / 개발환경 개선 / 스킬 개발 / 프로세스 개선)가 한 번만 시드된다.

## 구조

```
dash.py / server.py   진입점. 파싱·위임·출력만
app/services/         여러 엔티티에 걸치는 로직 (보드 트리, 계획)
app/repositories/     엔티티별 저장·조회와 정합성 규칙
app/db.py             연결·스키마·트랜잭션
static/               ES 모듈 프론트엔드 (번들러 없음)
```

## 규칙 몇 가지

- 우선순위는 워크스페이스 순위 + 할일 순서로만 표현한다. **할일은 중요도가 아니라 착수 가능한 순서로 놓는다.**
- 카테고리는 그룹핑 분류일 뿐 우선순위 계산에 관여하지 않는다.
- 카테고리 삭제는 비어 있을 때만. 워크스페이스 삭제 시 소속 할일은 미분류로 내려간다. 할일 삭제는 하위할일까지 지운다.
- 웹과 CLI가 같은 DB를 쓴다. CLI 변경을 웹에서 보려면 새로고침한다.

## 세션 연동 (②)

코드는 구현·검증 완료. **훅 등록은 아직 하지 않았다** — 아래 "훅 등록" 절차가 남았다.

```bash
python3 dash.py sessions                                  # 돌고 있는 세션
python3 dash.py classify <session> --category 개발 --workspace 2
python3 dash.py link-todo <session> 3
```

훅이 등록되면 세션이 열릴 때 자동 등록되고, 브랜치의 Jira ID가 워크스페이스와 맞으면 배경·목적·목표·할일이 주입된다. 아니면 세션이 스스로 카테고리를 정하고, 관련 워크스페이스가 추정되면 사용자 확인을 받아 붙는다.

### 훅 등록

`hooks/dash_hook.py` 의 **절대 경로**가 필요하다. 이 저장소를 워크트리에서 쓰고 있다면 워크트리가 지워질 때 훅이 깨지므로, 코드를 영구 경로(예: `~/work-dashboard` 본체)에 둔 뒤 등록한다.

`~/.claude/settings.json` 백업 후 네 이벤트에 각각 추가한다(마지막 인자만 이벤트명으로 바꿈).

```json
{"hooks": [{"type": "command", "command": "python3 <절대경로>/hooks/dash_hook.py SessionStart", "timeout": 2}]}
```

대상: `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd`.

같은 작업에서 `hooks.SessionStart` 의 `bash ~/.claude/skills/scope-guard/session-inject.sh` 항목을 **제거**한다. 남겨두면 같은 내용이 두 번 주입된다.

### scope-guard 흡수 (미적용)

`app/services/session_link.py` 의 `scope_guard_block()` 이 기존 `<scope-guard>` 블록 형식을 그대로 만들어낸다(테스트 통과). `~/.claude/skills/scope-guard/scope_db.py` 를 이 함수를 쓰는 어댑터로 교체하면 목표·하위단계가 대시보드의 워크스페이스·할일로 통합된다. 훅 등록과 마찬가지로 경로가 확정된 뒤에 적용한다.

### 롤백

훅 등록 후 문제가 생기면:

```bash
cp ~/.claude/settings.json.bak ~/.claude/settings.json
cp ~/.claude/skills/scope-guard/scope_db.py.bak ~/.claude/skills/scope-guard/scope_db.py
cp ~/.claude/scope-guard/scope.db.bak ~/.claude/scope-guard/scope.db
```

## 설계 문서

- 설계: `docs/superpowers/specs/2026-07-29-work-dashboard-design.md`
- 구현 계획: `docs/superpowers/plans/2026-07-29-work-dashboard.md`

## 아직 없는 것

- Claude 세션 매핑과 컨텍스트 자동 주입 (②)
- 결정 대기 큐 (③)
- 자율 실행 (④)
- scope-guard 흡수 — 지금은 scope-guard 가 자기 `scope.db` 를 계속 본다 (②에서 전환)
- 완료 항목 아카이브, 할일 의존성, 카테고리 우선순위
