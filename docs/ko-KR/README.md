# 작업 대시보드

[English](../../README.md) · **한국어** · [日本語](../ja-JP/README.md) · [中文](../zh-CN/README.md)

Claude Code 와 함께 일하는 사람을 위한 로컬 작업 관리 도구. 사람은 브라우저로,
Claude 는 CLI 로 다루고, 둘이 같은 sqlite 파일을 읽고 쓴다. 프레임워크도, 번들러도,
`pip install` 도 없다.

작업은 **카테고리 → 워크스페이스 → 할일** 3계층으로 관리한다. 그 위에서 Claude Code
세션 하나하나가 등록되고 워크스페이스로 분류되며 실제로 작업 중인 할일에 연결된다.
그래서 보드는 지금 무엇이 돌고 있는지를 항상 보여주고, 다음 세션은 어디까지 진행됐는지
알고 시작한다.

> [!NOTE]
> 1인용이고 인증이 없으며 외부 서비스를 쓰지 않는다. 전부 내 PC 의 sqlite 파일 하나에
> 들어 있다.

## 기능

- **3계층 보드** — 카테고리가 워크스페이스를 묶고, 워크스페이스가 할일을 담는다.
  우선순위는 순서만으로 표현하며, 전부 드래그로 재정렬한다.
- **세션 실시간 추적** — 훅이 Claude Code 세션을 등록하고 워크스페이스 컨텍스트를
  주입하며, 작업하는 동안 보드를 계속 맞춰 놓는다.
- **워크트리 관리** — 각 git 워크트리의 상태와 커밋을 보고, 그 워크트리의 개발 서버를
  보드에서 바로 실행·재실행·중지한다.
- **병합 한 커맨드** — 상태 확인 → 대상 브랜치 들이기 → 테스트 → 병합 → 할일·서버·
  브랜치 해제를 그 순서로 한다.
- **자율 실행** — 라벨이 붙은 할일 하나를 5분 크론으로 백그라운드 `claude` 잡에 맡긴다.
  기본은 꺼짐.
- **사용량 화면** — 로컬 Claude Code 로그에서 읽은 한도 창과 일별 토큰·비용 추이.
- **상태줄** — 지금 잡은 할일, 워크트리, 서버 포트를 Claude Code 상태줄에 그린다.
- **화면 언어 4종** — 영어(기본) · 한국어 · 일본어 · 중국어. 지구본 아이콘에서 바꾼다.

## 요구사항

| | |
| --- | --- |
| 필수 | Python 3.9+ (표준 라이브러리만), Git, 최신 브라우저 |
| 선택 | Claude Code — 세션 추적·상태줄·자율 실행에 필요 |
| 선택 | Node.js — 테스트 중 일부 화면 검증이 `node` 로 돈다 |
| 선택 | `PATH` 의 `markdownlint-cli2` — 마크다운 린트 훅이 쓴다 |

## 빠른 시작

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
./start.sh
```

`http://127.0.0.1:9080` 을 연다. DB 는 최초 연결 때 만들어지므로 마이그레이션이나
초기 설치 단계가 없다.

```bash
./start.sh --port 9081     # 다른 포트. 예를 들어 워크트리용
./restart.sh               # 이 디렉토리에서 띄운 서버를 다시 시작
./stop.sh                  # 중지
python3 server.py          # 포그라운드로 실행
```

`start.sh` 는 인자를 `server.py` 로 그대로 넘기고 pid 와 로그 경로를 출력한다. 로그는
하루 한 파일(`logs/YYYY-MM-DD.log`)이고, 7일 넘게 손대지 않은 파일은 다음 실행 때
지운다.

`stop.sh` 와 `restart.sh` 는 이 디렉토리를 작업 위치로 쓰는 서버만 건드린다. 워크트리
서버와 메인 체크아웃 서버가 서로를 죽이지 않는다.

> [!WARNING]
> `python3 server.py --host 0.0.0.0` 은 대시보드를 LAN 에 노출한다. 인증은 없다.

## 웹 화면

| 탭 | 내용 |
| --- | --- |
| 보드 | 전체 트리, 다음에 할 일, 돌고 있는 세션(2초 폴링), 자율 수행 스위치 |
| 워크스페이스 | 워크스페이스 생성과 배경·목적·목표·고려사항 편집 |
| 설정 | 카테고리와 라벨 |
| 사용량 | 한도 창과 토큰·비용 추이 |

보드에는 하위 탭이 둘 있다 — **할일**과 **워크트리**. 워크트리 하위 탭에서는 각 줄의
케밥 메뉴(⋮)로 그 워크트리를 적용(병합)·삭제하고, 서버를 실행·재실행·중지한다.

할일 줄과 세션 줄은 같은 팝업을 열고, 팝업은 탭 세 개다.

| 팝업 탭 | 내용 |
| --- | --- |
| 개요 | 제목, History, 착수 조건, 컨텍스트 노트 전문 |
| 세션 | 세션 id·위치·최근 대화 10건, 워크스페이스·카테고리 지정 |
| 워크트리 | 그 할일이 썼던 워크트리 — 상태·History·커밋 |

## CLI

`dash.py` 는 Claude Code 가 쓰는 진입점이다. 모든 명령이 웹과 같은 DB 를 보므로 한쪽의
변경은 다른 쪽에서 새로고침하면 보인다.

### 보드

```bash
python3 dash.py ls                                   # 전체 트리
python3 dash.py next                                 # 다음에 할 일 1건
python3 dash.py show <워크스페이스id|JIRA-1>           # 워크스페이스 상세
python3 dash.py add-category <이름>
python3 dash.py add-workspace <카테고리> <이름> [--background ...] [--jira KEY]
python3 dash.py add-todo <제목> [--workspace ID] [--note ...] [--precondition ...]
python3 dash.py move-todo <할일id> --workspace <id|none>
python3 dash.py set-status <todo|workspace> <id> <상태>
python3 dash.py reorder <categories|workspaces|todos> <ids...>
python3 dash.py done-today [--date YYYY-MM-DD]
```

### 세션

```bash
python3 dash.py sessions                             # 돌고 있는 세션
python3 dash.py classify --category <이름> [--workspace <id>]
python3 dash.py link-todo <할일id> [--status done]    # 이 세션이 할일을 잡는다
python3 dash.py show-todo --session
python3 dash.py show-note <할일id>                    # 컨텍스트 노트 전문
```

세션 인자는 생략할 수 있다. 생략하면 Claude Code 가 세션이 띄운 모든 프로세스에 넣어
주는 `CLAUDE_CODE_SESSION_ID` 로 자기 세션을 찾는다.

### 워크트리와 병합

```bash
python3 dash.py merge                        # 확인 → 대상 들이기 → 테스트 → 병합 → 해제
python3 dash.py merge --message "제목"        # 병합 커밋 제목
python3 dash.py merge --test "npm test"      # tests/__main__.py 가 없는 저장소
python3 dash.py merge --no-test
python3 dash.py finish [--worktree PATH]     # 해제만 — 할일 done + 서버 종료
python3 dash.py statusline <세션> [--cwd PATH]
```

`merge` 는 대상 브랜치를 워크트리에 들인 뒤에 테스트를 **한 번만** 돌린다. 테스트한
트리가 곧 병합될 트리다. 충돌로 멈추면 파일을 해결하고 `git add` 한 뒤 같은 명령을
다시 실행하면 이어받는다. push 는 하지 않고, 워크트리도 지우지 않는다 —
`ExitWorktree` 몫이다.

### 초기 설정·언어·자율 실행

```bash
python3 dash.py onboard [--skip]             # 초기 설정이 필요한 상태인지
python3 dash.py scan-history --days 7        # 지난 세션당 한 줄 요약
python3 dash.py language [en|ko|ja|zh]       # 인자가 없으면 현재 값
python3 dash.py usage                        # 한도 사용률과 토큰 추이
python3 dash.py autorun on|off|status
python3 dash.py autorun-tick [--dry-run]     # 5분 크론이 부르는 진입점
python3 dash.py autorun-prompt <할일id>       # 자율 세션에 실제로 들어가는 지시 전문
python3 dash.py autorun-request "<이유>"      # 판단 보류 — 사람 결정을 요청
python3 dash.py autorun-finish               # 완료 — 검토 대기로
```

## Claude Code 연동

### 세션 컨텍스트

훅은 세션마다 `<work-dashboard state="...">` 블록을 **하나만** 주입한다. 어떤 것이
들어가는지는 보드 상태에 달렸다.

| 상태 | 조건 | 주입 내용 |
| --- | --- | --- |
| `classified` | 브랜치의 Jira ID 로 매칭됐거나 `classify --workspace` 로 붙은 워크스페이스가 있음 | 배경·목적·목표·고려사항, 할일 목록, 범위 준수 지침 |
| `onboarding` | 워크스페이스가 하나도 없고 사용자가 거절한 적도 없음 | 초기 설정 절차 |
| `unclassified` | 그 외 | 현재 위치·브랜치, 카테고리, 진행 중 워크스페이스, 분류 절차 |
| `released` | 이 세션이 잡은 할일이 전부 `done` | 새 요청은 끝난 할일에 얹지 말고 새 할일로 받으라는 지시 |

분류 자체는 자동이 아니다 — 셸은 질문이 무엇에 관한 것인지 알 수 없다. 훅은 지시만
주입하고, Claude 가 `classify` 와 `link-todo` 로 직접 등록한다.

### 훅

모든 훅은 어떤 실패에서도 조용히 `exit 0` 으로 끝난다. 대시보드 문제로 세션이 안
열리거나 파일을 못 고치게 되는 일은 없어야 한다. `exit 2` 는 막는 것이 목적일 때만
쓴다.

| 훅 | 이벤트 | 하는 일 |
| --- | --- | --- |
| `hooks/dash_hook.py` | `SessionStart`, `UserPromptSubmit`, `Stop`, `SessionEnd` | 세션 등록·상태 추적과 위 컨텍스트 블록 주입 |
| `hooks/worktree_serve.py` | `Stop` | 고친 워크트리에 서비스 중인 서버가 없으면 막고 빈 포트(9080–9139)를 건네준다 |
| `hooks/worktree_guard.py` | `PreToolUse` (`Write`·`Edit`·`NotebookEdit`) | `~/work/` 메인 체크아웃의 소스 편집을 막는다. `ALLOW_MAIN_CHECKOUT=1` 로 우회 |
| `hooks/commit_scope_guard.py` | `PreToolUse` (`Bash`) | pathspec 없는 `git add -A`·`git commit -a` 를 막는다. `ALLOW_BROAD_COMMIT=1` 로 우회 |
| `hooks/md_lint.py` | `PostToolUse` (`Write`·`Edit`·`NotebookEdit`) | 이 저장소에 저장된 `.md` 를 `markdownlint-cli2` 로 검사 |
| `hooks/stale_base.py` | `UserPromptSubmit` | 브랜치가 upstream 또는 기준 브랜치보다 뒤처졌으면 세션당 한 번 경고 |

`worktree_serve.py` 는 이 저장소의 `.claude/settings.json` 에 이미 등록돼 있어 새로
clone 해도 따로 할 일이 없다. 나머지 다섯은 `~/.claude/settings.json` 에 절대 경로로
등록한다. 경로는 워크트리가 아니라 메인 체크아웃을 가리켜야 한다 — 워크트리는 병합
뒤 지워진다.

```json
{
  "hooks": [
    {
      "type": "command",
      "command": "python3 /절대경로/work-dashboard/hooks/dash_hook.py SessionStart",
      "timeout": 2
    }
  ]
}
```

`dash_hook.py` 는 이벤트 이름을 유일한 인자로 받으므로, 마지막 인자만 바꿔 이벤트마다
하나씩 추가한다.

### 상태줄

`~/.claude/statusline-command.js` 가 `dash.py statusline <세션> --cwd <경로>` 를 부르고
그 출력을 사용률 막대 아래 둘째 줄에 그린다.

```text
Context ████░░░░░░ 42% │ Usage ███░░░░░░░ 30% │ Weekly ██████░░░░ 55%
[doing | tab-underline | :9092] 보드에 할일·워크트리 탭 분리하고 워크트리 뷰 추가
```

대괄호 안은 항상 **상태 | 워크트리 | 포트** 순서이고, 없는 칸은 구분자까지 같이 빠진다.
셋 다 없으면 대괄호 자체가 없다.

### 자율 실행

`autorun on` 이면 5분 크론이 할일 하나를 골라 백그라운드 `claude` 잡으로 돌린다.
`auto` 라벨이 붙은 할일만 대상이다 — 자율 실행 허가는 사람이 주는 것이지 코드가
추정할 것이 아니다. 기본은 꺼짐이고 자동으로 다시 켜지는 경로는 없다.

```cron
*/5 * * * * /usr/bin/python3 /절대경로/work-dashboard/dash.py autorun-tick >/dev/null 2>&1
```

대상이 없는 tick 은 아무것도 하지 않는다. 데몬이 아니라 크론인 이유다.

## 설정

| 항목 | 위치 |
| --- | --- |
| DB | `~/.claude/work-dashboard/dash.db`. `WORK_DASHBOARD_DB` 로 덮어쓴다 |
| 호스트·포트 | `server.py --host` / `--port` (기본 `127.0.0.1:9080`) |
| 화면 언어 | 지구본 아이콘 또는 `dash.py language`. `meta.language` 에 저장 |
| 화면 문구 | `static/lang/{en,ko,ja,zh}.json`. 키가 서로 같고 영어가 폴백 |
| 디자인 토큰 | `static/css/app.css` 의 `:root` — 간격·글자·둥글기의 유일한 출처 |
| 마크다운 규칙 | `.markdownlint.json` |

## 데이터 모델

sqlite 를 웹 서버·CLI·훅이 직접 연다. 중재하는 프로세스는 없다. `connect()` 가 스키마를
만들고 외래키와 WAL 을 켜며 기본 카테고리 6개를 최초 1회만 시드한다. `*_at` 컬럼은
전부 ISO 8601 UTC 텍스트다.

| 테이블 | 역할 |
| --- | --- |
| `categories` | 최상위 그룹핑. 우선순위에는 관여하지 않는다 |
| `workspaces` | 브랜치·Jira 단위 작업. 배경·목적·목표·고려사항을 보관 |
| `todos` | 할일. 워크스페이스에 속하거나 카테고리 직속일 수 있다 |
| `labels`, `todo_labels` | 라벨은 할일의 성격이라 한 할일에 여럿 붙는다 |
| `sessions` | Claude Code 세션. 훅이 등록·갱신한다 |
| `session_todos` | 세션이 잡은 할일. 세션의 워크스페이스는 여기서 파생한다 |
| `worktrees` | 워크트리 이력. 병합·삭제로 디렉토리가 사라져도 남는다 |
| `usage_samples` | 사용량 화면이 쓰는 한도·토큰 샘플 |
| `autorun_state`, `autorun_runs` | 자율 실행 설정과 실행 기록 |
| `meta` | 단일 설정과 내부 플래그 |

## 프로젝트 구조

```text
work-dashboard/
├── dash.py               # CLI 진입점 — 파싱·위임·출력만
├── server.py             # HTTP 진입점 (http.server, 프레임워크 없음)
├── start.sh              # 백그라운드 실행, 날짜별 로그, 7일치 정리
├── stop.sh · restart.sh  # 이 디렉토리의 서버만 다룬다
├── serving.sh            # 서버 탐지·종료 공용 함수
├── app/
│   ├── constants.py      # 매직넘버는 전부 여기로
│   ├── db.py             # 연결·스키마·트랜잭션
│   ├── repositories/     # 엔티티별 저장·조회와 정합성 규칙
│   └── services/         # 여러 엔티티에 걸치는 로직
├── hooks/                # Claude Code 훅
├── static/               # ES 모듈 프론트엔드 (번들러 없음)
│   ├── index.html        # 단일 페이지. 문구 대신 data-i18n 키만 갖는다
│   ├── lang/             # en · ko · ja · zh, 키 집합이 같다
│   ├── css/              # app.css 가 토큰을 정의하고 usage.css 는 참조만
│   └── js/               # boot·i18n·board·workspace·sessions·usage·chart
├── tests/                # python3 -m tests
└── docs/superpowers/     # 설계 문서와 계획
```

## 테스트

```bash
python3 -m tests
```

리포지토리·서비스·CLI·훅을 덮고, 네 언어 파일의 키와 자리표시자가 일치하는지 보며,
CSS 의 간격·글자가 생 px 이 아니라 디자인 토큰을 쓰는지 강제한다. 화면 동작 검증은
`node` 로 돌고 같은 이름의 파이썬 테스트가 부른다.

## 설계 문서

`docs/superpowers/specs/` 에 단계별 설계와 확정 결정이, `docs/superpowers/plans/` 에
구현 계획이 있다.
