# 작업 대시보드 (work-dashboard)

Claude Code 세션과 할 일을 한곳에서 관리하는 로컬 대시보드입니다. Python 표준 라이브러리와 sqlite 만으로 동작하며, 웹 화면·CLI·hook 세 가지 경로로 같은 데이터를 다룹니다.

## 주요 기능

- **보드** — 카테고리 > 워크스페이스 > 할일 > 하위할일 트리를 그리고, 드래그로 순서를 바꿉니다. 라벨은 한 할일에 여러 개 붙습니다.
- **세션 연동** — hook 이 Claude Code 세션을 등록하고, 세션에 필요한 context 를 주입합니다. 세션을 워크스페이스로 분류하면 지시 원문에서 할일을 만들어 붙입니다.
- **워크트리 관리** — 저장소별 브랜치와 워크트리 현황을 보여주고, 서버 실행·재실행·중지와 병합·버리기를 화면에서 수행합니다.
- **사용량 추이** — 5시간·7일 한도 사용률과 모델별 토큰·비용 추이를 차트로 그립니다.
- **자율 실행** — `auto` 라벨이 붙은 할일을 `claude --bg` 잡으로 한 건씩 실행하고, 끝나면 검토 대기 상태로 회수합니다.
- **가드 hook** — 메인 체크아웃 소스 편집, 전체 스테이징·전체 커밋을 차단하고, 낡은 베이스 위 착수를 경고합니다.

## 시작하기

### 사전 요구사항

**필수:**

- Python 3 — 외부 의존성이 없습니다. 표준 라이브러리만 사용합니다.
- Git — 워크트리·브랜치 조회와 병합에 사용합니다.
- Bash — 실행 스크립트가 bash 3.2 에서도 동작합니다.

**선택:**

| 도구 | 없을 때 동작 |
| --- | --- |
| Node.js | 프론트엔드 검증 테스트 10건을 건너뜁니다 |
| `markdownlint-cli2` | markdown lint hook 이 검사를 통과시킵니다 |
| `claude` CLI | 할일 제목 요약과 자율 실행이 동작하지 않습니다 |

### 설치

내려받는 것으로 끝입니다. 설치 명령이 따로 없습니다.

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
```

데이터베이스는 첫 실행 때 `~/.claude/work-dashboard/dash.db` 에 자동으로 만들어지고, 스키마와 기본 카테고리도 함께 들어갑니다.

### 실행

```bash
./start.sh
```

서버가 뜨면 주소 한 줄과 프로세스 id 를 출력합니다.

```text
http://127.0.0.1:9080
pid 41207 · 로그 logs/2026-08-05.log
```

포트를 바꾸려면 인자를 넘깁니다. 인자는 `server.py` 로 그대로 전달됩니다.

```bash
./start.sh --port 9081
```

멈추거나 다시 띄울 때는 다음 스크립트를 사용합니다. 세 스크립트 모두 현재 디렉토리를 cwd 로 돌고 있는 서버만 다루므로, 다른 워크트리에서 띄운 서버는 건드리지 않습니다.

| 명령 | 설명 |
| --- | --- |
| `./start.sh [인자]` | 백그라운드로 실행합니다. 로그는 `logs/YYYY-MM-DD.log` 에 쌓고 7일이 지나면 지웁니다 |
| `./stop.sh` | 이 디렉토리에서 돌고 있는 서버를 종료합니다 |
| `./restart.sh [인자]` | 종료하고 다시 실행합니다. 인자를 생략하면 종료한 서버의 인자를 물려받습니다 |

포그라운드로 직접 실행할 수도 있습니다.

```bash
python3 server.py --port 9080
```

## 사용법

### 웹 화면

브라우저에서 `http://127.0.0.1:9080` 을 엽니다. 왼쪽 탭 네 개가 각각 사용량, 보드, 워크스페이스, 설정을 담당하고, 보드 탭 안에는 할일·세션·워크트리·자율 실행 하위 탭이 있습니다. 탭 경로(`/board` 등)에는 파일이 없고 서버가 `index.html` 을 돌려주면 화면이 라우팅합니다.

### CLI

`dash.py` 는 웹 화면과 같은 데이터를 다룹니다. 조회 명령에 `--json` 을 붙이면 Claude 가 파싱할 수 있는 형태로 출력합니다.

**조회:**

| 명령 | 설명 |
| --- | --- |
| `ls [--group-by workspace\|category]` | 전체 트리 개요 |
| `next [--workspace ID]` | 다음에 할 일 1건 |
| `show <워크스페이스 id 또는 Jira ID>` | 워크스페이스 상세 |
| `show-todo [--workspace ID]` | 할일 목록 (id·제목·context 유무) |
| `show-note <todo_id>` | 할일 context 전문 |
| `done-today [--date YYYY-MM-DD]` | 그날 완료한 항목 |
| `sessions` | 활성 세션 목록 |
| `usage` | 한도 사용률과 토큰 추이 |
| `statusline <session_id> [--cwd 경로]` | 상태줄 한 줄 |

**등록과 수정:**

| 명령 | 설명 |
| --- | --- |
| `add-category <name>` | 카테고리 추가 |
| `add-workspace <category> <name>` | 워크스페이스 추가 (`--background`·`--purpose`·`--goal`·`--considerations`·`--jira`) |
| `add-todo <title>` | 할일 추가 (`--category`·`--workspace`·`--note`·`--precondition`) |
| `add-subtask <todo_id> <title>` | 하위할일 추가 |
| `move-todo <todo_id> --workspace <id 또는 none>` | 할일을 다른 워크스페이스로 이동 |
| `set-status <todo\|subtask\|workspace> <id> <status>` | 상태 변경 |
| `reorder <종류> [--scope ID] <id...>` | 순서 변경 |
| `rm-category <id> [--force]` | 카테고리 삭제 |

**세션과 병합:**

| 명령 | 설명 |
| --- | --- |
| `classify <session_id> [--category NAME] [--workspace ID]` | 세션 분류 등록 |
| `link-todo <session_id> <todo_id>` | 세션이 만든 할일 연결 |
| `merge <session_id>` | 워크트리 브랜치를 master 로 병합 (상태 확인·테스트·해제까지) |
| `finish <session_id>` | 병합 후 리소스 해제 (할일 done·서버 종료) |
| `scan-history [--days 7\|14]` | 초기 설정용 히스토리 요약 |
| `onboard [--skip]` | 초기 설정 상태 |

**자율 실행:**

| 명령 | 설명 |
| --- | --- |
| `autorun <on\|off\|status>` | 켜기·끄기·상태 |
| `autorun-tick [--dry-run]` | 실행 판정 (5분 cron 이 호출) |
| `autorun-prompt <todo_id>` | 자율 세션에 줄 지시 전문 |
| `autorun-finish <session_id>` | 자율 수행 완료 — 검토 대기로 전환 |
| `autorun-request <session_id> <note>` | 판단 보류 — 사람 결정 요청 |
| `autorun-reopen <run_id>` | 확인을 되돌려 다시 검토 대기로 |

세션 id 를 받는 명령은 값을 생략할 수 있습니다. 생략하면 `CLAUDE_CODE_SESSION_ID` 가 가리키는 세션을 사용하므로, Claude Code 세션 안에서는 id 를 적지 않아도 됩니다. 터미널에서 직접 실행할 때는 값을 적습니다.

### 예제

할일을 하나 만들고 트리와 다음 할 일을 확인합니다.

```bash
python3 dash.py add-todo "README 초안 작성" --category "개발"
python3 dash.py ls
python3 dash.py next
```

출력은 다음과 같습니다.

```text
1. README 초안 작성
미분류  0/1
  [todo] 1. README 초안 작성
미분류 / README 초안 작성
```

자율 실행 상태를 확인합니다.

```bash
python3 dash.py autorun status
```

```text
autorun: off (연속 막힘 0, 마지막 tick 없음)
```

### 테스트

테스트는 표준 라이브러리 `unittest` 로 돌립니다. Python 테스트 34건과 Node.js 로 확인하는 프론트엔드 검증 10건이 있습니다.

```bash
python3 -m tests
```

## 설정

### 환경 변수

| 이름 | 기본값 | 설명 |
| --- | --- | --- |
| `WORK_DASHBOARD_DB` | `~/.claude/work-dashboard/dash.db` | 데이터베이스 경로. 테스트는 임시 경로를 넘겨 사용합니다 |
| `CLAUDE_CODE_SESSION_ID` | 없음 | CLI 가 자기 세션을 알아내는 값. Claude Code 가 하위 프로세스에 실어 보냅니다 |
| `ALLOW_MAIN_CHECKOUT` | 없음 | `1` 이면 메인 체크아웃 편집 차단을 통과합니다 |
| `ALLOW_BROAD_COMMIT` | 없음 | `1` 이면 전체 스테이징·전체 커밋 차단을 통과합니다 |

### 기본값

| 항목 | 값 |
| --- | --- |
| 호스트 | `127.0.0.1` |
| 포트 | `9080` |
| 기본 카테고리 | 개발, 운영, 장애 대응, 개발환경 개선, 스킬 개발, 프로세스 개선 |
| 로그 보관 | 7일 |
| 자율 실행 동시 실행 | 1건 |

세부 상수는 `app/constants.py` 한 곳에 모여 있습니다.

### hook 등록

저장소가 공유하는 등록은 `.claude/settings.json` 한 건입니다. 워크트리에서 웹 프로젝트를 고쳤는데 그 코드를 서비스하는 프로세스가 없으면 세션 종료를 막습니다.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$CLAUDE_PROJECT_DIR/hooks/worktree_serve.py\"",
            "timeout": 10
          }
        ]
      }
    ]
  }
}
```

나머지 hook 은 저장소 밖에서도 동작해야 하므로 `~/.claude/settings.json` 에 전역으로 등록합니다.

| 파일 | 이벤트 | 역할 |
| --- | --- | --- |
| `hooks/dash_hook.py` | SessionStart, UserPromptSubmit, Stop, SessionEnd | 세션 등록·상태 갱신과 context 주입 |
| `hooks/stale_base.py` | UserPromptSubmit | 낡은 베이스 위 착수를 경고 |
| `hooks/worktree_guard.py` | PreToolUse | 메인 체크아웃 소스 편집 차단 |
| `hooks/commit_scope_guard.py` | PreToolUse | 전체 스테이징·전체 커밋 차단 |
| `hooks/md_lint.py` | PostToolUse | 저장한 `.md` 파일을 검사 |

등록 예시는 다음과 같습니다. 경로는 실제 저장소 위치로 바꿉니다.

```json
{
  "type": "command",
  "command": "python3 /Users/me/work/work-dashboard/hooks/dash_hook.py SessionStart"
}
```

모든 hook 은 자체 오류에서 통과(exit 0)합니다. hook 이 세션을 막는 사고가 더 크기 때문입니다.

### 자율 실행 cron

판정은 5분 cron 이 호출합니다. 별도 데몬을 두지 않습니다.

```text
*/5 * * * * /usr/bin/python3 /Users/me/work/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

## API 레퍼런스

모든 응답은 `application/json; charset=utf-8` 입니다. 경로가 `/api/` 로 시작하지 않으면 정적 파일이나 `index.html` 을 돌려줍니다.

### 엔드포인트 목록

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET | /api/tree | 보드 트리 조회 |
| GET | /api/next | 다음에 할 일 1건 조회 |
| GET | /api/done-today | 완료 항목 조회 |
| GET | /api/categories | 카테고리 목록 조회 |
| GET | /api/labels | 라벨 목록 조회 |
| GET | /api/workspaces | 워크스페이스 목록 조회 |
| GET | /api/workspaces/{id} | 워크스페이스와 그 할일 조회 |
| GET | /api/todos/{id} | 할일 상세 조회 |
| GET | /api/sessions | 활성 세션 조회 |
| GET | /api/sessions/{id} | 세션 상세 조회 |
| GET | /api/usage | 사용량 스냅샷 조회 |
| GET | /api/worktrees | 워크트리 현황 조회 |
| GET | /api/autorun | 자율 실행 상태와 실행 기록 조회 |
| POST | /api/categories | 카테고리 생성 |
| POST | /api/labels | 라벨 생성 |
| POST | /api/workspaces | 워크스페이스 생성 |
| POST | /api/todos | 할일 생성 |
| POST | /api/subtasks | 하위할일 생성 |
| POST | /api/reorder | 순서 변경 |
| POST | /api/worktrees | 워크트리 병합·버리기·서버 조작 |
| PATCH | /api/categories/{id} | 카테고리 수정 |
| PATCH | /api/labels/{id} | 라벨 수정 |
| PATCH | /api/workspaces/{id} | 워크스페이스 수정 |
| PATCH | /api/todos/{id} | 할일 수정 |
| PATCH | /api/subtasks/{id} | 하위할일 수정 |
| PATCH | /api/sessions/{id} | 세션 분류 |
| PATCH | /api/autorun | 자율 실행 켜기·끄기 |
| PATCH | /api/autorun-runs/{id} | 검토 대기를 완료로 확인 |
| DELETE | /api/categories/{id} | 카테고리 삭제 |
| DELETE | /api/labels/{id} | 라벨 삭제 |
| DELETE | /api/workspaces/{id} | 워크스페이스 삭제 |
| DELETE | /api/todos/{id} | 할일 삭제 |
| DELETE | /api/subtasks/{id} | 하위할일 삭제 |

### GET /api/tree

보드 트리를 조회합니다.

**요청 파라미터:**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| group_by | string | 아니오 | 묶는 기준. `workspace` 또는 `category` (기본값: `workspace`) |

**응답 예시:**

```json
{
  "group_by": "workspace",
  "groups": [
    {
      "kind": "unassigned",
      "id": null,
      "name": "미분류",
      "sort_order": null,
      "done_count": 0,
      "total_count": 0,
      "todos": []
    }
  ]
}
```

### POST /api/todos

할일을 생성합니다. 카테고리나 워크스페이스 중 하나는 반드시 지정합니다.

**요청 본문:**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| title | string | 예 | 할일 제목 |
| category_id | number | 조건부 | 카테고리 id |
| workspace_id | number | 조건부 | 워크스페이스 id. 지정하면 카테고리는 여기서 따라옵니다 |
| note | string | 아니오 | 이 할일에만 필요한 context |
| precondition | string | 아니오 | 착수 가능 조건. 참·거짓이 갈리는 한 문장을 첫 줄에 씁니다 |

### DELETE /api/categories/{id}

카테고리를 삭제합니다.

**요청 파라미터:**

| 이름 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| force | string | 아니오 | `1` 이면 분류된 세션을 미분류로 내리고 삭제합니다 |

## 에러 처리

서버는 도메인 예외의 타입만 보고 상태 코드를 정합니다. 메시지 문자열로 분기하지 않습니다.

| 상태 코드 | 예외 | 의미 |
| --- | --- | --- |
| 400 | `Validation` | 입력값이 규칙을 위반했습니다 |
| 404 | `NotFound` | 대상 리소스가 없습니다 |
| 404 | `UnknownEndpoint` | 경로 자체가 등록되지 않았습니다 |
| 409 | `Conflict` | 현재 상태와 충돌하는 요청입니다 |
| 409 | `NeedsConfirm` | 되돌리기 어려워 사용자 확인이 필요합니다 |
| 500 | 그 외 | 예상하지 못한 오류입니다 |

에러 응답은 `error` 필드 하나로 옵니다.

```json
{
  "error": "알 수 없는 엔드포인트"
}
```

`NeedsConfirm` 만 `confirm` 플래그를 함께 보냅니다. 화면은 사용자에게 되묻고 같은 요청에 `?force=1` 을 붙여 다시 보냅니다.

```json
{
  "error": "분류된 세션이 있습니다",
  "confirm": true
}
```

## 문제 해결

| 증상 | 원인 | 해결 |
| --- | --- | --- |
| `포트 9080 를 열 수 없음` | 이미 그 포트를 쓰는 서버가 있습니다 | `./stop.sh` 로 내리거나 `./start.sh --port 9081` 로 다른 포트를 씁니다 |
| `이 디렉토리에서 돌고 있는 서버 없음` | 서버가 다른 디렉토리를 cwd 로 돌고 있습니다 | 그 디렉토리에서 `./stop.sh` 를 실행합니다 |
| 화면이 뜨는데 API 가 404 | 프론트엔드가 부르는 경로가 서버에 없습니다 | `python3 -m tests` 를 돌립니다. `tests/test_frontend_contract.py` 가 미등록 경로를 잡아냅니다 |
| 세션이 대시보드에 안 보임 | `dash_hook.py` 가 등록되지 않았습니다 | `~/.claude/settings.json` 에 이벤트 네 건을 등록합니다 |
| 사용량이 낡은 값으로 표시 | 사용률은 statusline 이 그려질 때만 갱신됩니다 | 정상 동작입니다. 15분이 지나면 낡음 표시가 붙습니다 |
| 자율 실행이 아무것도 시작하지 않음 | 후보가 없거나 사용률을 읽지 못했습니다 | `python3 dash.py autorun-tick --dry-run` 으로 판정 사유를 확인합니다 |
| 테스트 일부가 skip | Node.js 가 없습니다 | 프론트엔드 검증까지 확인하려면 Node.js 를 설치합니다 |

## 라이선스

저장소에 라이선스 파일이 없습니다. 배포 전에 라이선스를 정해 추가해 주세요.
