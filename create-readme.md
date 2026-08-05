# 작업 대시보드

![Python](https://img.shields.io/badge/Python-3.9%2B-3776ab?style=flat-square&logo=python&logoColor=white)
![Dependencies](https://img.shields.io/badge/dependencies-0-2aa77a?style=flat-square)
![Tests](https://img.shields.io/badge/tests-524%20passing-2aa77a?style=flat-square)
![SQLite](https://img.shields.io/badge/storage-SQLite-003b57?style=flat-square&logo=sqlite&logoColor=white)

돌고 있는 Claude Code 세션과 내가 쌓아둔 할 일을 한 화면에서 잇는 로컬 대시보드.
어떤 세션이 어느 작업을 하는 중인지, 다음에 뭘 집어야 하는지, 한도를 얼마나 태웠는지를
브라우저·터미널·상태줄 어디서든 같은 값으로 본다.

[개요](#개요) • [시작하기](#시작하기) • [화면](#화면) • [CLI](#cli) • [훅](#훅) • [자율 실행](#자율-실행) • [API](#api) • [테스트](#테스트) • [문제 해결](#문제-해결)

> [!NOTE]
> 개인 로컬 도구다. `127.0.0.1` 에만 바인딩하고 인증이 없으며, 홈 디렉토리의 Claude Code
> 기록(`~/.claude/`)을 읽는다. 공용 호스트에 띄우는 것을 전제로 만들지 않았다.

## 개요

세션 훅이 대시보드에 세션을 등록하고, 대시보드는 그 세션에게 "너는 어느 워크스페이스의
어느 할 일을 하는 중"이라는 컨텍스트를 되돌려준다. 사람은 브라우저에서 순서를 정하고,
Claude 는 CLI 로 같은 DB 를 읽고 쓴다.

```text
Claude Code 세션 ──▶ hooks/dash_hook.py ──┐
브라우저 ──▶ static/ ──▶ server.py ───────┤──▶ app/services ──▶ app/repositories
터미널 ──▶ dash.py ───────────────────────┘                          │
                                                                     ▼
                                            sqlite ~/.claude/work-dashboard/dash.db
```

| 구성 | 위치 | 역할 |
| --- | --- | --- |
| HTTP 진입점 | `server.py` | 라우팅과 JSON 직렬화만. 도메인 로직 없음 |
| CLI 진입점 | `dash.py` | 파싱·위임·출력만. Claude 와 상태줄이 쓰는 입구 |
| 도메인 | `app/services/` | 보드 조립, 병합, 자율 실행, 사용량 집계, 세션 컨텍스트 |
| 데이터 접근 | `app/repositories/` | SQL 전담 |
| 스키마·연결 | `app/db.py` | `connect()` 하나만 외부에 노출 |
| 상수 | `app/constants.py` | 포트·경로·임계값·사용자 문구를 전부 여기 모음 |
| 화면 | `static/` | 의존성 없는 ES 모듈 + CSS. 빌드 단계 없음 |
| 훅 | `hooks/` | 세션 추적과 작업 가드 |

주요 기능:

- **세션 ↔ 할 일 연결** — 세션이 시작하면 훅이 등록하고, 분류될 때까지 지시 블록을 다시 주입한다
- **보드** — 카테고리/워크스페이스로 묶은 할 일, 하위 할 일, 라벨, 드래그 정렬
- **워크트리 뷰** — 워크스페이스별 저장소의 브랜치·워크트리·떠 있는 포트를 한 줄씩. 병합·버리기·서버 실행까지 그 줄에서
- **병합 파이프라인** — 상태 확인 → 대상 브랜치 들이기 → 테스트 → 병합 → 리소스 해제를 한 명령으로
- **사용량** — 5시간·주간 한도 창, 일별 토큰과 비용, 주차 비교, 계정별 트랙 분리
- **자율 실행** — 사람이 `auto` 라벨로 허가한 할 일 1건을 `claude --bg` 잡으로 돌리고 결과를 회수
- **착수 조건** — 참/거짓이 갈리는 한 문장. 조건이 붙은 할 일은 자율 실행 후보에서 빠진다

## 시작하기

### 요구 사항

- Python 3.9 이상 — 표준 라이브러리만 쓴다. `pip install` 할 것이 없다
- Claude Code — 세션 추적, 사용량, 자율 실행이 `~/.claude/` 를 읽는다
- (선택) `markdownlint-cli2` — `hooks/md_lint.py` 가 쓴다. 없으면 훅이 조용히 통과한다

### 실행

```bash
git clone <이 저장소> work-dashboard
cd work-dashboard
./start.sh
```

첫 실행에서 `~/.claude/work-dashboard/dash.db` 를 만들고 기본 카테고리(개발, 운영,
장애 대응, 개발환경 개선, 스킬 개발, 프로세스 개선)를 넣는다. 스크립트는 URL 한 줄을
찍고 빠지며, 로그는 `logs/YYYY-MM-DD.log` 에 쌓고 7일 지난 것을 지운다.

| 스크립트 | 하는 일 |
| --- | --- |
| `./start.sh [--port 9081] [--host 0.0.0.0]` | 백그라운드로 띄운다. 인자는 `server.py` 로 그대로 넘어간다 |
| `./stop.sh` | **이 디렉토리를 cwd 로 돌던** 서버만 멈춘다 |
| `./restart.sh [인자]` | 멈추고 다시 띄운다. 인자를 생략하면 죽는 서버의 포트를 물려받는다 |

기본 주소는 `http://127.0.0.1:9080` 이다. 포그라운드로 보고 싶으면 `python3 server.py`
를 직접 부른다.

> [!TIP]
> 세 스크립트 모두 cwd 로 대상을 가린다. 워크트리마다 다른 포트로 띄워도 서로의 서버를
> 죽이지 않는다 — 여러 브랜치를 동시에 띄워 비교할 때 이 성질에 기댄다.

### 훅 등록

세션 추적은 훅이 없으면 아무것도 안 한다. `~/.claude/settings.json` 에 네 이벤트를 등록한다.

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [{ "type": "command", "command": "python3 ~/work/work-dashboard/hooks/dash_hook.py SessionStart" }] }
    ],
    "UserPromptSubmit": [
      { "hooks": [{ "type": "command", "command": "python3 ~/work/work-dashboard/hooks/dash_hook.py UserPromptSubmit" }] }
    ],
    "Stop": [
      { "hooks": [{ "type": "command", "command": "python3 ~/work/work-dashboard/hooks/dash_hook.py Stop" }] }
    ],
    "SessionEnd": [
      { "hooks": [{ "type": "command", "command": "python3 ~/work/work-dashboard/hooks/dash_hook.py SessionEnd" }] }
    ]
  }
}
```

상태줄까지 붙이면 진행 중인 할 일과 워크트리 포트가 프롬프트 옆에 붙는다.

```bash
python3 ~/work/work-dashboard/dash.py statusline --cwd "$PWD"
```

### 환경 변수

| 변수 | 용도 |
| --- | --- |
| `WORK_DASHBOARD_DB` | DB 경로 교체. 테스트와 실험은 이걸로 사용자 DB 를 피한다 |
| `CLAUDE_CODE_SESSION_ID` | 세션이 띄운 프로세스에 실려온다. CLI 가 이걸로 자기 세션을 안다 |
| `ALLOW_MAIN_CHECKOUT` | `worktree_guard.py` 우회 |
| `ALLOW_BROAD_COMMIT` | `commit_scope_guard.py` 우회 |

## 화면

경로가 곧 탭이다(`/board`, `/usage`, …). 모르는 경로는 기본 탭으로 떨어지고, 새로고침은
제자리로 돌아온다.

| 탭 | 보는 것 |
| --- | --- |
| 사용량 | 한도 창, 토큰 추이, 모델별 비중, 주차 비교. 진입 시 기본 탭 |
| 보드 | 다음에 할 일, 자율 수행 패널, 돌고 있는 세션, 할 일 트리. 하위 탭으로 워크트리 |
| 워크스페이스 | 배경·목적·목표·고려사항과 소속 할 일 |
| 설정 | 카테고리(소속, 하나)와 라벨(성격, 여럿), 색 |

세션 줄을 누르면 최근 대화가 뜬다. 원문은 DB 가 아니라 Claude Code 의 transcript
jsonl 에 있어서, 세션 id 로 파일을 찾아 꼬리만 읽는다.

> [!IMPORTANT]
> 한도 %는 Claude Code 가 상태줄 페이로드로만 넘기는 값이라, `token-optimizer` 상태줄이
> 떨어뜨린 사이드카 파일에서 읽는다. 세션이 조용한 동안 값이 낡는 것은 정상이며 화면이
> 낡음 표시를 붙인다. 사이드카가 없으면 사용량 탭은 한도 없이 토큰 추이만 그린다.

## CLI

`dash.py` 는 사람이 아니라 주로 Claude 가 쓴다. 대부분의 조회 명령은 `--json` 을 받는다.
세션 인자를 생략하면 `CLAUDE_CODE_SESSION_ID` 가 가리키는 세션으로 본다.

```bash
python3 dash.py ls --group-by category
python3 dash.py add-todo "빠른 추가 폼 정리" --workspace 12 --precondition "#57 이 done 일 것"
python3 dash.py next --json
python3 dash.py merge --message "빠른 추가 폼 정리"
```

| 명령 | 하는 일 |
| --- | --- |
| `ls` | 전체 트리 개요 (`--group-by workspace\|category`) |
| `next` | 다음에 할 일 1건 |
| `show <id\|JIRA>` | 워크스페이스 상세 |
| `show-todo`, `show-note <id>` | 할 일 목록, 컨텍스트 전문 |
| `done-today [--date]` | 그날 완료분 |
| `add-category`, `add-workspace`, `add-todo`, `add-subtask` | 등록 |
| `move-todo`, `set-status`, `reorder`, `rm-category` | 수정·정렬·삭제 |
| `sessions` | 활성 세션 목록 |
| `classify <session>` | 세션을 카테고리·워크스페이스로 분류 |
| `link-todo <session> <todo-id>` | 세션이 잡은 할 일 연결 |
| `merge` | 병합 파이프라인 한 번에 |
| `finish` | 병합 뒤 리소스 해제 (할 일 done, 서버 종료) |
| `statusline` | 상태줄 한 줄. 보여줄 게 없으면 아무것도 안 찍는다 |
| `usage` | 한도 사용률과 토큰 추이 |
| `scan-history`, `onboard` | 초기 설정용 히스토리 요약과 진행 상태 |
| `autorun on\|off\|status` | 자율 실행 스위치 |
| `autorun-tick`, `autorun-prompt`, `autorun-reopen` | 판정, 지시 전문 확인, 검토 되돌리기 |
| `autorun-request`, `autorun-finish` | 자율 세션이 스스로 판단 보류·완료 표시 |

### 병합

`merge` 는 LLM 이 매번 손으로 조립하던 순서를 한 단계로 고정한 것이다.

```text
상태 확인 → 대상 브랜치 들이기 → 테스트 → 병합 → 리소스 해제
```

대상 브랜치를 먼저 들여서 테스트하므로 그 트리가 병합 결과와 같고, 병합 뒤에 다시
테스트할 필요가 없다. 중단 사유가 있으면 어디까지 갔는지 찍고 그 사유로 실패한다.
`push` 는 하지 않는다 — 원격 반영은 사람 몫이다. 워크트리 디렉토리 제거도 하지 않는다
(에이전트의 cwd 가 그 안이라 밖에서 지우면 셸이 깨진다).

### 워크트리

보드의 워크트리 하위 탭은 워크스페이스마다 저장소 하나, 그 아래 브랜치·워크트리 행을
그린다. 저장소 경로는 어디에도 저장돼 있지 않고 **그 워크스페이스에서 돌았던 세션의
cwd 로 유추한다** — 세션이 한 번도 안 돈 워크스페이스는 그리지 않는다. 조회는 git·lsof 를
읽기 전용으로만 부르고, 실패하면 그 칸만 비운다.

케밥 메뉴가 상태를 바꾸는 셋을 부른다.

| 동작 | 하는 일 |
| --- | --- |
| 적용 | 병합 → 서버 종료 → 워크트리·브랜치 제거 → 할 일 done |
| 버리기 | 병합 없이 버린다 |
| 띄우기 / 다시 띄우기 / 내리기 | 서버만. 포트는 9080–9139 에서 고른다 |

> [!NOTE]
> 서버 실행은 대상 워크트리 루트의 `run.sh` 하나만 본다. 없으면 실행하지 않고 그 사실을
> 알린다 — 진입점을 추측해 띄우면 엉뚱한 프로세스가 포트를 문다.

## 훅

| 훅 | 이벤트 | 하는 일 |
| --- | --- | --- |
| `dash_hook.py` | SessionStart · UserPromptSubmit · Stop · SessionEnd | 세션 등록·상태 갱신, 분류 컨텍스트 주입 |
| `worktree_serve.py` | Stop | 워크트리를 고쳤는데 서비스하는 프로세스가 없으면 종료를 막는다 |
| `worktree_guard.py` | PreToolUse | `~/work/` 메인 체크아웃의 소스 편집 차단 (문서·설정은 통과) |
| `commit_scope_guard.py` | PreToolUse | `git add -A`, `git commit -a` 등 전체 스테이징·커밋 차단 |
| `stale_base.py` | UserPromptSubmit | 브랜치가 upstream 이나 기준 브랜치보다 뒤처졌으면 한 줄 경고 |
| `md_lint.py` | PostToolUse | 저장된 `.md` 를 `markdownlint-cli2` 로 검사 |

`worktree_serve.py` 만 저장소의 `.claude/settings.json` 에 등록돼 있다. 나머지는 사용자
설정에 붙이는 전역 훅이다.

> [!IMPORTANT]
> 모든 훅은 자기 오류에서 fail-open 이다(exit 0, 무출력). 훅 버그로 편집이나 세션 종료를
> 막는 사고가 훅이 한 번 안 도는 것보다 크다. 의도한 차단만 exit 2 로 나간다.

## 자율 실행

사람이 자리를 비운 사이 할 일 1건씩 `claude --bg` 잡으로 돈다. 기본값은 꺼짐이고,
자동으로 다시 켜지는 경로는 없다. 5분 크론으로 판정을 부른다.

```cron
*/5 * * * * /usr/bin/python3 ~/work/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

대상은 두 겹으로 좁힌다 — 사람이 붙인 `auto` 라벨, 그리고 **착수 조건 문장의 부재**.
조건은 자연어라 코드가 충족 여부를 판정할 수 없으므로 조건이 붙은 할 일은 후보에서 뺀다.
우선순위는 `next` 와 같은 로직을 그대로 쓴다 — 자율 실행이 다른 기준으로 고르면 사람이
보는 순서와 어긋난다.

시작하지 않는 사유:

| 사유 | 뜻 |
| --- | --- |
| `autorun 이 꺼져 있음` | 스위치가 off |
| `자율 잡 수행중` | 동시 실행은 1건 |
| `5시간 창 사용률이 한도에 닿음` | 90% 이상 |
| `사용률 데이터가 아예 없음` | 모르면 안 돈다 |
| `돌릴 수 있는 할일이 없음` | `auto` 라벨 후보 없음 |
| `그 워크스페이스에서 작업하던 위치를 알 수 없음` | 세션 cwd 로 저장소를 못 찾음 |
| `작업 위치에 커밋 안 된 변경이 있음` | 남의 diff 에 얹지 않는다 |

결과는 다섯 가지다. `review`(검토 대기)가 성공한 잡의 **첫** 결과이고, `done` 은 사람이
검토 대기 배지를 눌러 내렸을 때만 붙는다 — 진행 중과 검토 대기를 같은 배지로 뭉개면
사람이 무엇을 봐야 하는지 목록에서 알 수 없다. `requested`(요청)는 실패가 아니라 세션이
스스로 멈춘 것이라 실패 횟수에 세지 않는다.

| 결과 | 뜻 |
| --- | --- |
| `review` | 다 끝냈고 사람이 보고 병합을 판정할 차례 |
| `done` | 사람이 검토를 마쳤다 |
| `failed` | 실패. 같은 할 일이 2회 연속이면 막고 다음으로 |
| `blocked` | 한도 등으로 막혔다. 3회 연속이면 autorun 자체를 끈다 |
| `requested` | 기획 공백·방향 미정 등으로 사람 결정을 기다린다 |

> [!WARNING]
> 자율 세션은 커밋하지 않는다. 금지 목록(`git commit`/`push`, 외부 전송, 삭제성 명령,
> 의존성 설치)은 프롬프트 규칙이며 기술적 차단 장치가 아니다. **커밋·푸시 금지가 안전망**
> 이다 — 규칙을 넘어선 변경도 워킹트리에 남으므로 `git diff` 로 전부 보이고
> `git checkout` 으로 되돌아간다. 띄우기 전에 `autorun-prompt <todo-id>` 로 실제 들어가는
> 지시를 눈으로 볼 수 있다.

자율 세션에 사람이 말을 걸면 그 잡을 사람 것으로 인계하고 autorun 을 끈다.

## API

전부 `/api/` 아래이고 JSON 을 주고받는다. 그 밖의 경로는 `static/` 을 서비스하며,
확장자가 없는 경로는 `index.html` 로 떨어져 화면이 라우팅한다.

| 메서드 | 경로 | 하는 일 |
| --- | --- | --- |
| GET | `/api/tree?group_by=` | 보드 트리 |
| GET | `/api/next`, `/api/done-today?date=` | 다음 할 일, 완료분 |
| GET | `/api/categories`, `/api/labels` | 목록 |
| GET | `/api/workspaces[/{id}]` | 목록 또는 상세 + 소속 할 일 |
| GET | `/api/todos/{id}` | 할 일 상세 |
| GET | `/api/sessions[/{id}]` | 활성 세션 또는 상세 + 최근 대화 |
| GET | `/api/usage`, `/api/worktrees`, `/api/autorun` | 사용량, 워크트리, 자율 실행 |
| POST | `/api/categories`, `/api/labels`, `/api/workspaces`, `/api/todos`, `/api/subtasks` | 생성 |
| POST | `/api/reorder` | `kind` + `ids` + `scope_id` 로 정렬 |
| POST | `/api/worktrees` | `action`: `apply` · `discard` · `start` · `restart` · `stop` |
| PATCH | `/api/{categories,labels,workspaces,todos,subtasks}/{id}` | 부분 수정 |
| PATCH | `/api/sessions/{id}` | 분류. 워크스페이스로 분류하면 할 일까지 만들어 붙인다 |
| PATCH | `/api/autorun`, `/api/autorun-runs/{id}` | 스위치, 검토 확인 |
| DELETE | `/api/{categories,labels,workspaces,todos,subtasks}/{id}` | 삭제 (`?force=1`) |

상태 코드는 도메인 예외 타입만 보고 정한다 — `NotFound` 404, `Conflict` 409,
`Validation` 400, 그 밖 500. 되물어야 하는 삭제는 응답에 `"confirm": true` 를 실어
보내고, 클라이언트가 확인한 뒤 `?force=1` 로 다시 요청한다.

## 테스트

```bash
python3 -m tests
```

524개가 20초대에 돈다. 외부 러너 없이 `unittest` 만 쓴다. 서버·스크립트 테스트는
`WORK_DASHBOARD_DB` 를 임시 파일로 돌려 사용자 DB 를 건드리지 않는다.

프런트엔드는 `tests/*_check.mjs` 를 짝지어 두고 Python 테스트가 `node` 로 실행한다.
`tests/test_frontend_contract.py` 와 `tests/test_css_tokens.py` 는 화면과 서버가 같은
필드·토큰을 보는지 검사하고, `tests/test_precondition.py` 는 착수 조건 안내 문구가
CLI 도움말과 팝업에서 갈라지지 않았는지 본다.

## 문제 해결

| 증상 | 원인과 해결 |
| --- | --- |
| `포트 9080 를 열 수 없음` | 이미 떠 있다. `./restart.sh` 또는 `./start.sh --port 9081` |
| `./stop.sh` 가 "돌고 있는 서버 없음" | 스크립트는 cwd 로 대상을 가린다. 서버를 띄운 그 디렉토리에서 실행할 것 |
| 사용량 탭에 한도가 안 보임 | 사이드카(`~/.claude/token-optimizer/rate-limits.json`)가 없다. 토큰 추이는 그대로 나온다 |
| 한도 %가 낡았다고 표시됨 | 정상이다. 상태줄이 그려질 때만 갱신되므로 15분이 지나면 낡음 표시가 붙는다 |
| 세션이 대시보드에 안 뜸 | 훅이 등록되지 않았다. [훅 등록](#훅-등록) 참고. 훅은 실패해도 조용하다 |
| 워크스페이스가 워크트리 탭에 없음 | 그 워크스페이스에서 세션이 한 번도 안 돌아 저장소를 모른다 |
| 할 일이 done 으로 안 내려감 | 하위 할 일이 남아 있다. 먼저 끝내거나 지울 것 |
| 자율 실행이 안 돎 | `dash.py autorun-tick --dry-run` 으로 사유를 본다 |
| 세션 저장소에 `*.db` 가 생겼다 | 잔여물이다. 실 DB 는 `~/.claude/work-dashboard/dash.db` 다. 추적되면 dirty 판정이 서서 자율 실행이 멈춘다 |
