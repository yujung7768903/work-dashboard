# 작업 대시보드

카테고리 > 워크스페이스 > 할일 > 하위할일 4계층으로 작업을 관리하는 1인용 로컬 도구.
사람은 웹으로, Claude는 CLI로 같은 sqlite DB를 쓴다. 외부 의존성 0.

## 실행

```bash
python3 server.py                    # http://127.0.0.1:9080
python3 server.py --host 0.0.0.0     # 폰에서 볼 때 (인증 없음, LAN 노출 주의)
```

## 테스트

```bash
python3 -m tests
```

## 프로젝트 구조

```text
work-dashboard/
│
├── dash.py                          # CLI 진입점. 파싱·위임·출력만
├── server.py                        # 웹 서버 진입점 (http.server, 프레임워크 없음)
│
├── app/                             # 도메인 계층
│   ├── constants.py                 # 전역 상수. 매직넘버는 전부 여기로
│   ├── db.py                        # 연결·스키마·트랜잭션
│   ├── errors.py                    # 도메인 예외
│   ├── ordering.py                  # 정렬 순서 계산 공용 로직
│   │
│   ├── repositories/                # 엔티티별 저장·조회와 정합성 규칙
│   │   ├── categories.py            # 카테고리
│   │   ├── workspaces.py            # 워크스페이스
│   │   ├── todos.py                 # 할일
│   │   ├── subtasks.py              # 하위할일
│   │   └── sessions.py              # 세션 등록·분류·상태·할일 연결·정리
│   │
│   └── services/                    # 여러 엔티티에 걸치는 로직
│       ├── board.py                 # 보드 트리 조립
│       ├── planning.py              # 다음에 할 일 선정
│       ├── session_link.py          # 세션 주입 블록 조립
│       ├── session_todo.py          # 웹에서 워크스페이스로 분류할 때 할일 자동 생성
│       ├── summary.py               # 지시문 한 줄 요약 (claude CLI 호출, 실패 시 None)
│       ├── release.py               # 병합 후 리소스 해제 (할일 done·서버 종료)
│       ├── transcript.py            # Claude Code jsonl 읽기 (앞·꼬리 조각)
│       ├── history.py               # 초기 설정용 히스토리 스캔·요약
│       └── usage.py                 # 한도 사용률·토큰 추이
│
├── hooks/
│   ├── dash_hook.py                 # Claude Code 훅 단일 진입점
│   ├── worktree_serve.py            # Stop: 고친 워크트리에 서버가 없으면 띄우라고 지시
│   └── worktree_guard.py            # PreToolUse: 메인 체크아웃 소스 편집 차단 (미등록)
│
├── static/                          # ES 모듈 프론트엔드 (번들러 없음)
│   ├── index.html                   # 단일 페이지
│   ├── css/
│   │   ├── app.css                  # 디자인 토큰 정의 + 공통·보드 스타일
│   │   └── usage.css                # 사용량 화면 전용 (토큰은 app.css 것을 참조)
│   └── js/
│       ├── main.js                  # 부트스트랩·탭 전환 (/usage /board 등 경로 = 탭)
│       ├── api.js                   # fetch 래퍼
│       ├── board.js                 # 보드 렌더
│       ├── categories.js            # 카테고리 관리
│       ├── workspace.js             # 워크스페이스 상세
│       ├── sessions.js              # 활성 세션 (2초 폴링)
│       ├── usage.js                 # 사용량 화면
│       ├── chart.js                 # 차트 렌더
│       └── dnd.js                   # 드래그 재정렬
│
├── tests/                           # python3 -m tests 로 일괄 실행
│   ├── __main__.py                  # 러너
│   ├── support.py                   # 임시 DB 픽스처
│   └── test_*.py                    # 계층별 테스트
│
└── docs/superpowers/                # 설계·계획 문서
    ├── specs/                       # 단계별 설계와 확정 결정
    └── plans/                       # 구현 계획
```

## 훅 동작

`hooks/dash_hook.py <이벤트>` 하나가 네 이벤트를 분기한다. `~/.claude/settings.json` 에 절대 경로로 등록돼 있고 타임아웃은 2초. **어떤 실패에서도 `exit 0` 무출력으로 끝난다** — 대시보드 문제로 Claude 세션이 안 열리는 것이 최악의 실패이기 때문이다.

| 시점 | 이벤트 | 하는 일 | 세션에 주입되는 것 |
| --- | --- | --- | --- |
| 세션이 열릴 때 | `SessionStart` | stdin JSON 의 `session_id`·`cwd` 로 세션 등록, `cwd` 에서 `git branch --show-current` 조회, 브랜치의 Jira ID 로 워크스페이스 자동 매칭 | 워크스페이스 블록 또는 분류 지시 블록 |
| 지시를 넣을 때마다 | `UserPromptSubmit` | 상태를 `working` 으로, 마지막 지시를 120자로 잘라 저장 | 분류 전이면 분류 지시 재주입, 잡은 할일을 모두 끝냈으면 새 할일 지침, 그 외 무출력 |
| 응답이 끝날 때 | `Stop` | 상태를 `idle` 로 | 없음 |
| 세션이 닫힐 때 | `SessionEnd` | 상태를 `ended` 로, 종료 시각 기록 | 없음 |

### 워크트리 서버 훅 (`hooks/worktree_serve.py`)

워크트리에서 코드를 고쳐 놓고 확인할 화면을 안 띄우면, 사용자는 결과를 눈으로 볼 수 없다. 이 `Stop` 훅이 그걸 막는다.

- **등록 위치가 다르다.** `~/.claude/settings.json`(그 PC 전용, 절대 경로)이 아니라 저장소에 커밋되는 `.claude/settings.json` 에 `$CLAUDE_PROJECT_DIR` 기준으로 등록된다. 그래서 clone 한 다른 PC에서도 따로 설정할 것이 없다.
- **거는 조건**: 이번 세션에 `.claude/worktrees/<이름>/` 안의 파일을 고쳤고, 그 워크트리에 `server.py`·`manage.py`·`package.json` 중 하나가 있고(= 띄울 수 있는 프로젝트), cwd 가 그 워크트리인 서버 프로세스가 없을 때.
- **이미 떠 있으면 관여하지 않는다.** 다른 세션이 그 화면을 보고 있을 수 있어 재기동하지 않는다.
- 막으면서 빈 포트(9080–9139)를 골라 주고, 응답을 `- 워크트리:` / `- url:` / `- 작업 요약:` 세 줄로 끝내라고 지시한다.
- 프로세스 탐지는 `app/services/release.py` 의 것을 그대로 쓴다(아래 "병합 후 리소스 해제" 참고). `stop_hook_active` 면 통과해 무한 루프를 막고, 어떤 실패에서도 `exit 0` 으로 fail-open 한다.

주입 블록은 네 갈래다.

| 상황 | 블록 | 내용 |
| --- | --- | --- |
| 브랜치의 Jira ID = 워크스페이스의 `jira_id` | `<work-dashboard state="classified">` | 배경·목적·목표·고려사항 + 할일 목록(컨텍스트 노트 유무 표시) + 범위 준수 지침 |
| 워크스페이스가 0개이고 사용자가 거절한 적 없음 | `<work-dashboard state="onboarding">` | 초기 설정 절차 7단계 (아래 참고) |
| 그 외 | `<work-dashboard state="unclassified">` | 현재 위치·브랜치, 카테고리 6개, 진행 중 워크스페이스 목록, 분류 절차 지시 |
| 분류됐고 잡은 할일이 **전부 `done`** (프롬프트 시점) | `<work-dashboard state="released">` | 새 요청은 끝난 할일에 얹지 말고 새 할일로 받으라는 지시 |

모든 블록 꼬리에 공통 규칙이 붙는다 — 다른 세션이 같은 코드·문서를 고칠 수 있으니 착수 전에 최신 상태를 다시 읽으라는 것. `classified`·`unclassified` 에는 아래 해제 절차도 함께 붙는다.

분류는 훅이 못 한다(셸은 질문 내용을 이해할 수 없다). 훅이 넘긴 지시를 받아 Claude 가 아래 명령으로 직접 등록하고, 분류 전이면 매 프롬프트마다 지시가 다시 들어간다.

```bash
python3 dash.py sessions                                  # 돌고 있는 세션
python3 dash.py classify <session> --category 개발 --workspace 2
python3 dash.py link-todo <session> 3                     # 세션이 잡은 할일 연결
```

### 웹에서 분류하면 할일까지 만든다

세션 줄을 눌러 팝업에서 **워크스페이스로** 분류하면(`PATCH /api/sessions/<id>`) 그 자리에서 할일을 하나 만들고 세션에 연결한다(`app/services/session_todo.py`). 카테고리만 고르면 만들지 않는다 — 워크스페이스 없는 세션은 대개 단발 조회다.

CLI 로 분류할 때는 Claude 가 지시를 읽고 직접 만들지만, 웹에서 누르는 순간에는 그 자리에 Claude 가 없다. 그러면 보드는 그 작업을 모르고 다음 세션도 무엇을 하던 중인지 알 수 없다. 그래서 **코드가 판단할 수 있는 것만** 만든다.

| 항목 | 근거 | 규칙 |
|------|------|------|
| 제목 | 만들 때는 첫 지시의 첫 문장(60자에서 자름), 곧이어 **한 줄 요약**으로 교체 (아래) | 목록 표기로 시작하는 줄은 항목이라 제목이 못 된다 |
| `note` | 지시 원문 앞 5건 | 위치·브랜치·세션 id + 원문. 요약하지 않는다 — 제목이 요약이므로 근거는 여기에만 남는다 |
| 하위할일 | 목록 표기(`-`, `*`, `1.`) 항목 → 없으면 첫 지시의 요청 문장(`~해줘`, `~주고`) | 2개 미만이면 만들지 않고(할일과 같은 말), 8개에서 끊는다 |

#### 제목 요약 (`app/services/summary.py`)

지시 원문을 그대로 제목에 쓰면 보드가 구구절절해진다 — "워크스페이스에서 하위할일이 펼쳐진 상태로 보이는데, 너무 길어져서 기본적으로…". 어미만 떼는 식의 규칙으로는 줄지 않는다(요약은 의미 판단이다). 그래서 **이미 깔려 있는 `claude` CLI** 를 부른다.

```bash
claude -p --model <haiku> --tools "" --strict-mcp-config --setting-sources "" \
  --exclude-dynamic-system-prompt-sections --system-prompt "<제목 요약 지시>" "<지시 원문>"
```

하네스를 전부 끄는 것이 핵심이다. 기본값으로 부르면 도구·MCP·CLAUDE.md·스킬까지 얹혀 **1분이 넘고, 지시를 작업으로 착각해 파일을 고치려 든다**(실제로 "권한이 필요합니다" 가 응답으로 왔다). 끄면 7~8초에 한 줄만 돌아온다.

- 결과가 비었거나 `SUMMARY_MAX_CHARS` 를 넘으면 **요약이 아니라 설명**이므로 버린다
- **요약은 기다리지 않는다.** 분류 응답(`PATCH`)은 지시 첫 문장을 제목으로 한 할일을 바로 돌려주고(실측 0.25초), 요약은 뒷일(daemon 스레드, `session_todo.retitle`)이 뒤따라 제목만 갈아 끼운다. 동기로 기다리던 때는 저장 버튼이 8초쯤 멈춘 것처럼 보였다. 뒷일은 **자기 sqlite 연결을 새로 연다** — 요청 스레드의 연결은 다른 스레드에서 쓸 수 없고(`ProgrammingError`), 경로가 비면 `connect()` 가 사용자의 실제 DB 로 떨어지므로 그때는 아무것도 하지 않는다
- 만들 때 `note` 에 "제목: 요약이 붙지 않아 지시 첫 문장을 그대로 씀"(`AUTO_TODO_NOTE_RAW_TITLE`) 을 남기고, 요약이 붙으면 그 줄을 지운다. 남아 있으면 조회 결과에 `needs_title: true` 로 실려 **보드 줄과 팝업 개요에 `요약 안 됨` 배지**가 붙는다 — 손봐야 할 제목을 사용자가 알아야 하기 때문이다. 컬럼을 늘리지 않고 `note` 한 줄로 판단하므로 그 줄을 지우면 배지도 사라진다
- 그 사이 사용자가 제목을 고쳤으면 요약이 덮지 않는다. 요약이 실패하면 제목·`note` 를 그대로 둔다 — 요약 하나 때문에 할일이 안 생기면 안 된다
- **실패는 이유를 로그로 남긴다** (`제목 요약 실패: …`). 조용히 `None` 을 돌려주던 동안은 화면에 배지만 뜨고 왜 안 붙었는지 알 방법이 없었다. 실제로 첫 라이브 실행에서 조용히 실패한 원인이 타임아웃이었고, 뒷일은 아무도 기다리지 않으므로 `SUMMARY_TIMEOUT_SEC` 을 60초로 뒀다. CLI 는 stdin 을 3초 기다리다 경고를 뱉으므로 `stdin=DEVNULL` 로 넘긴다
- 하위할일은 요약하지 않는다 — 제목만으로 보드 가독성 문제가 해결되고, 호출을 늘릴 이유가 없다

지시 원문은 transcript 앞 64KB 에서 읽는다. 이때만 `parse_line(collapse=False)` 로 **줄바꿈을 살린다** — 목록 표기를 봐야 하기 때문이다(팝업 대화 목록은 한 줄로 뭉갠 기본값을 쓴다). transcript 를 못 찾으면 훅이 저장한 마지막 지시 한 줄로 대신하고, 그것도 없으면 만들지 않는다.

이미 잡은 할일이 있는 세션은 건드리지 않는다 — 그게 이 세션의 작업이고, 새로 만들면 같은 일이 두 줄이 된다. 만들어진 뒤 팝업은 닫히지 않고 **개요 탭**으로 넘어가 제목·하위할일·`note` 를 보여준다. 추정으로 만든 것이므로 사용자가 바로 보고 고칠 수 있어야 한다.

### 병합 후 리소스 해제

master 에 병합하면 작업은 끝났는데 리소스는 세 개가 남는다 — **연결된 할일**, **그 워크트리를 띄워둔 서버**, **워크트리 디렉토리**. 남겨두면 보드에는 끝난 일이 `doing` 으로 계속 뜨고, 죽은 브랜치의 서버가 포트를 물고 있는다.

```bash
python3 dash.py finish <session>                 # 연결된 할일 done + 그 워크트리의 서버 종료
python3 dash.py finish <session> --worktree PATH # 자동으로 못 찾을 때 직접 지정
```

종료 대상 워크트리는 **`--worktree` → transcript 에 남은 마지막 워크트리 cwd → 세션 DB 의 cwd** 순서로 찾는다. 세션 DB 의 cwd 는 SessionStart 훅이 세션이 열릴 때 적은 값이라 `EnterWorktree` 로 옮겨간 뒤에는 메인 체크아웃을 가리키기 때문이다 — Claude Code transcript 는 줄마다 그때의 cwd 를 남기므로 꼬리에서 마지막 워크트리 경로를 읽는다. 그래서 워크트리에서 작업한 세션도 옵션 없이 `finish <session>` 한 번으로 서버까지 정리된다.

찾지 못했을 때는 `(없음)` 으로 조용히 넘기지 않는다. 워크트리를 못 찾았으면 **본 경로**를, 워크트리는 찾았지만 그 cwd 를 쓰는 서버가 없으면 그 경로를 함께 찍는다 — 서버가 남은 것을 모르고 지나가면 죽은 브랜치가 포트를 물고 있는다.

워크트리 제거는 이 명령이 하지 않는다 — Claude 의 cwd 가 그 안이라 밖에서 지우면 셸이 깨진다. `ExitWorktree` 툴이 나가면서 지우는 것이 맞는 순서다(**서버를 먼저 죽이고** 나간다).

종료 대상은 두 겹으로 좁힌다. 잘못 죽이면 사용자가 보던 화면이 꺼지기 때문이다.

- 경로에 `/.claude/worktrees/` 가 없으면 아예 훑지 않는다 → 메인 체크아웃의 대시보드 서버는 안전
- 명령줄에서 **플래그·`VAR=값`·`nohup`·`env` 를 걷어낸 앞 두 토큰**만 보고 서버인지 판단한다 → `python3 -u server.py`, `nohup env WORK_DASHBOARD_DB=... python3 server.py` 처럼 띄운 서버도 찾고, `zsh -c '... server.py ...'` 같은 자기 셸은 죽이지 않는다 (실행 위치는 프로세스의 cwd 로 이미 걸렀다)

프로세스 탐지(`app/services/release.py`)는 `/proc` 이 있으면 그걸로, 없으면(macOS) `lsof -a -d cwd -t` 로 한다. `worktree_serve.py` 훅의 "서버가 떠 있는가" 판정도 같은 함수를 쓴다 — 훅이 떠 있다고 본 프로세스를 `finish` 가 종료하므로 둘의 판정이 갈리면 안 된다.

해제 뒤 같은 세션에서 사용자가 새 요청을 하면 `released` 블록이 주입돼 **새 할일을 만들어** 이어간다. 별도 플래그는 두지 않는다 — 새 할일을 `link-todo` 하는 순간 "전부 done" 이 깨져 블록이 저절로 조용해진다.

### 초기 설정 (⑤)

워크스페이스가 하나도 없는 상태에서 세션을 열면 분류 대신 **초기 설정 블록**이 주입된다. Claude 가 사용자에게 최근 며칠 치 히스토리를 볼지(7일 / 14일 / 안 함) 묻고, 스캔 결과로 카테고리·워크스페이스를 제안한 뒤 확인받아 등록한다.

```bash
python3 dash.py scan-history --days 7     # 세션당 한 줄 요약 (Claude 가 읽는 입력)
python3 dash.py onboard                   # 초기 설정이 필요한 상태인지
python3 dash.py onboard --skip            # 자동 분류 거절. 이후 다시 묻지 않음
python3 dash.py link-todo 56510381 4 --past   # 할일을 뽑아낸 근거 세션 연결
```

각 줄 맨 앞의 8자가 세션 id 앞머리이고, 그대로 `link-todo ... --past` 에 넘긴다. `--past` 는 `sessions` 에 없는 세션을 **`state=ended` 로** 등록한다 — `register()` 를 쓰면 `idle` + 지금 시각이 되어 이미 끝난 세션 수십 개가 활성 목록에 살아 있는 것처럼 뜬다. 앞머리가 둘 이상 맞으면 실패한다. 또 `--past` 는 할일 상태를 바꾸지 않는다. 보통의 `link-todo` 는 착수 선언이라 `todo` → `doing` 으로 올리지만, 끝난 세션 연결은 기록이지 착수가 아니기 때문이다.

`scan-history` 는 `~/.claude/projects/*/*.jsonl` **전체**에서 mtime 이 기간 안인 파일만 골라 **앞 64KB** 만 읽고, 프로젝트 위치별로 묶어 세션당 한 줄(시작~최근 날짜 + 첫 지시 200자)로 뱉는다. 전문은 수백 MB 라 세션에 넣을 수 없기 때문이다. 슬래시 명령·자동 압축 요청은 첫 지시에서 걸러낸다.

**묶는 것과 하한선 적용은 코드가 아니라 Claude 가 한다** — 의미 판단이라 셸이 못 한다. 세션 `ONBOARDING_MIN_SESSIONS`건 미만인 묶음은 워크스페이스로 만들지 않고 "기타" 한 줄로만 표시한다. 확인 트리가 검수 가능한 크기를 넘으면 사용자가 읽지 않고 승인하게 되기 때문이다.

묶는 단위는 **작업 위치(디렉토리) 하나 = 워크스페이스 하나**다. 한 저장소 안의 기획·구현·배포는 워크스페이스가 아니라 **착수 순서대로 놓는 할일**이다 — 워크스페이스로 쪼개면 `classified` 블록이 주입할 배경·목적이 세션마다 갈린다. 홈·scratch 성격의 위치만 내용으로 다시 쪼갠다.

할일마다 **그 할일을 뽑아낸 근거 세션을 연결하고**, 그 세션에서 착수할 때 필요한 구체 정보를 뽑아 `note` 에 적는다 — 실패한 명령과 오류 문구, 확정된 수치·기준, 제외한 범위, 참고 경로. 할일 자체가 그 세션에서 나온 것이므로 근거를 버리면 "왜 있는 할일인지" 를 히스토리에서 다시 찾아야 한다.

워크스페이스마다 **할일도 함께 만들고 상태까지 추정해 넣는다.** 보드가 할일 0개인 워크스페이스를 통째로 감추기 때문이다(`board.py` 의 `if not todos: continue`) — 워크스페이스만 만들면 화면에 아무것도 안 나타나 초기 설정이 실패한 것처럼 보인다. 추정이 틀려도 보드에서 바로 고칠 수 있다.

워크스페이스 필드를 채울 때의 기준은 **"매 세션 주입돼도 값어치가 있는가"** 하나다.

| 필드 | 넣는 것 | 안 넣는 것 |
| --- | --- | --- |
| 배경 | 왜 이 일이 존재하는가. 도메인의 문제 | 기술 스택, URL, 포트, 저장소 주소 |
| 목적 | 그 문제를 어떤 방향으로 푸는가 | 완료 조건 |
| 목표 | 끝났다고 판정할 수 있는 상태 | 방향·이유 |
| 고려사항 | 벗어나면 안 되는 제약·금지 | 구현 디테일, 일시적 이슈 |
| 할일 `note` | 그 할일 착수할 때만 필요한 구체 정보 | 워크스페이스 전체에 걸린 것 |

완료 플래그는 두지 않는다 — 워크스페이스가 하나라도 생기면 트리거 조건이 저절로 깨진다. 거절만 `meta.onboarding_declined` 에 남는다. 따라서 **워크스페이스를 전부 지우면 초기 설정이 다시 뜬다**(의도된 동작).

`link-todo` 는 `session_todos` 에 연결만 하고 할일 상태는 바꾸지 않는다 — 착수 시 `doing` 전환은 아직 없다(할일 32).

세션 정리는 별도 크론 없이 조회할 때 함께 수행한다 — `last_seen_at` 이 24시간 지난 `idle` 은 `ended` 로 간주하고, `ended` 이면서 연결된 할일이 없는 세션은 7일 뒤 삭제한다.

## 상태줄

Claude Code 상태줄에 **이 세션이 잡은 할일과 상태, 작업 중인 워크트리, 그 위치를 서비스하는 서버 포트**를 붙인다. 워크트리를 여럿 띄워 놓으면 지금 창이 어느 작업·어느 워크트리이고 어느 포트를 보는 창인지가 상태줄만 봐도 갈린다.

```
Context ████░░░░░░ 42% │ Usage ███░░░░░░░ 30% │ Weekly ██████░░░░ 55%
[doing | tab-underline | :9092] 보드에 할일·워크트리 탭 분리하고 워크트리 뷰 추가
```

대괄호 안은 **상태 | 워크트리 | 포트** 순서로 고정이고, 없는 칸은 구분자까지 같이 빠진다(`[master | :9080]`, `[wt-a]`). 셋 다 없으면 대괄호 자체가 없다.

**둘째 줄**에 그린다 — 막대 세 개와 같은 줄에 두면 좁은 창에서 제목이 먼저 잘린다.

```bash
python3 dash.py statusline <session> [--cwd PATH]   # 상태줄 한 줄. 보여줄 게 없으면 무출력
```

- **등록 위치**: `~/.claude/statusline-command.js`(그 PC 전용). 상태줄 슬롯은 하나뿐이라 이 스크립트가 사용률 막대까지 같이 그린다. 거기서 `python3 <메인 체크아웃>/dash.py statusline <세션> --cwd <현재 위치>` 를 부르고, **실패하면 빈 문자열로 넘긴다** — 대시보드 문제로 상태줄이 깨지면 안 된다. 워크트리가 아니라 메인 체크아웃 경로를 부르는 이유는 워크트리가 병합 뒤 지워지기 때문이다.
- **할일**: 연결된 것 중 안 끝난 첫 할일의 상태와 제목(40자에서 자름), 나머지는 뒤에 `+N` 으로. 끝난 것을 앞세우면 지금 뭘 하는지가 가려진다.
- **워크트리**: 워크트리 디렉토리 이름. 워크트리가 아니면 세션 DB 의 브랜치 이름(메인 체크아웃은 보통 `master`). 브랜치가 아니라 디렉토리 이름을 먼저 쓰는 이유는 세션 DB 의 브랜치가 SessionStart 때 값이라 `EnterWorktree` 로 옮겨간 뒤에는 메인 것을 가리키기 때문이다.
- **포트**: 그 디렉토리를 cwd 로 쓰는 프로세스가 듣고 있는 포트. 워크트리면 그 워크트리의 서버, 메인 체크아웃이면 거기서 도는 서버다. 위치는 `finish` 와 같은 순서(`--cwd` → transcript 의 마지막 워크트리 → 세션 DB 의 cwd)로 찾는다.
- **`finish` 와 다른 lsof 경로를 쓴다.** 종료 쪽 `lsof -a -d cwd -t <경로>` 는 전체 프로세스를 훑어 300ms 가 걸려 렌더링마다 쓸 수 없다. 상태줄은 듣고 있는 소켓 목록을 먼저 받고(40ms) 그 pid 들만 cwd 로 확인한다(40ms). 죽이지 않고 읽기만 하므로 워크트리 안으로 제한하지 않는다.

## 데이터베이스

- **DB**: sqlite3 (파이썬 표준 라이브러리 `sqlite3`, 외부 드라이버 없음)
- **위치**: `~/.claude/work-dashboard/dash.db`. 환경변수 `WORK_DASHBOARD_DB` 로 덮어쓸 수 있고, `connect(path)` 인자가 있으면 그게 최우선
- **접근 주체**: 웹 서버·CLI·훅이 같은 파일을 직접 연다. 서버 프로세스가 중재하지 않음

`app/db.py` 의 `connect()` 가 최초 호출될 때 하는 일 (매 연결마다 실행되지만 전부 멱등):

- DB 파일의 부모 디렉터리를 `makedirs(exist_ok=True)` 로 생성
- `PRAGMA foreign_keys=ON` — 참조 무결성 강제
- `PRAGMA journal_mode=WAL` — 웹·CLI·훅 동시 접근 대비
- `PRAGMA busy_timeout=5000` — 잠금 대기 5초
- `CREATE TABLE IF NOT EXISTS` 로 테이블 7개 생성
- 카테고리 6개(개발 / 운영 / 장애 대응 / 개발환경 개선 / 스킬 개발 / 프로세스 개선) 시드. `meta` 의 `categories_seeded` 플래그로 **최초 1회만** — 사용자가 지운 카테고리가 되살아나면 안 되기 때문

시각 컬럼(`*_at`)은 전부 TEXT 이며 ISO8601 UTC 초 단위(`2026-07-31T04:12:33+00:00`).

### 테이블 구조

| 테이블 | 역할 | 주요 컬럼 | 참조 |
| --- | --- | --- | --- |
| `categories` | 최상위 그룹핑. 우선순위 계산에는 관여 안 함 | `id`, `name`(UNIQUE), `sort_order`, `created_at`, `google_list_id`(구글 목록 연결) | — |
| `workspaces` | 브랜치·Jira 단위 큰 작업. 배경·목적·목표·고려사항 보관 | `id`, `name`, `background`, `purpose`, `goal`, `considerations`, `status`(active/paused/done), `sort_order`, `jira_id`, `created_at`, `updated_at` | `category_id` → `categories` |
| `todos` | 할일. 워크스페이스 없이 카테고리 직속도 가능 | `id`, `title`, `note`(컨텍스트 노트), `status`(todo/doing/done), `sort_order`, `completed_at`, `created_at`, `updated_at`, `google_task_id`(구글 태스크 연결) | `category_id` → `categories`, `workspace_id` → `workspaces` (nullable) |
| `subtasks` | 하위할일. 할일 삭제 시 함께 삭제 | `id`, `title`, `status`(todo/doing/done), `sort_order`, `created_at` | `todo_id` → `todos` |
| `sessions` | Claude Code 세션. 훅이 등록·갱신 | `id`, `claude_session_id`(UNIQUE), `cwd`, `git_branch`, `state`(working/idle/ended), `last_prompt`(120자), `started_at`, `last_seen_at`, `ended_at` | `category_id` → `categories`, `workspace_id` → `workspaces` (둘 다 nullable = 미분류) |
| `session_todos` | 세션 ↔ 할일 N:N 연결 | `created_at`, PK = (`session_id`, `todo_id`) | `session_id` → `sessions`, `todo_id` → `todos` |
| `meta` | 내부 플래그 저장소. `categories_seeded`, `onboarding_declined`, `gtasks_seen_ids` | `key`(PK), `value` | — |

## 구글 태스크 양방향 동기화

폰에서 할일을 보고 체크하려고 붙였다. 카테고리 하나가 구글 목록 하나(`대시보드 · <카테고리>`)로 간다.

### 최초 1회 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만들고 **Google Tasks API** 를 켠다
2. **사용자 인증 정보 → OAuth 클라이언트 ID → 데스크톱 앱** 으로 클라이언트를 만든다
3. 인증한다 (브라우저가 열리고, 승인하면 `~/.claude/work-dashboard/gtasks.json` 에 저장된다)

```bash
python3 dash.py gtasks-auth --client-id <ID> --client-secret <SECRET>
```

### 동기화

웹훅이 없는 API라 주기적으로 부르는 것 말고 방법이 없다. cron 이나 훅에 걸어 둔다.

```bash
python3 dash.py gtasks-sync --dry-run   # 무엇이 바뀔지만 보고 아무것도 안 씀
python3 dash.py gtasks-sync
```

**첫 실행은 `--dry-run` 으로 확인한다** — 미완료 할일 전부가 구글에 생성된다.

### 동기화 규칙

| 항목 | 방향 | 충돌 시 |
| --- | --- | --- |
| 제목 | 양방향 | `updated_at` vs `updated` 최신 우선 |
| 완료 여부 | 양방향 | 위와 같음 |
| note·착수 조건 | 내려보내기만 | 폰에서 고쳐도 대시보드는 안 바뀜 |
| 하위할일 | 동기화 안 함 | — |

- **내용이 실제로 다를 때만** 시각을 본다. 안 그러면 우리가 방금 민 것 때문에 원격이 늘 최신이라 무한 왕복이 된다.
- 시각은 초 단위로 잘라서 비교한다. `db.now()` 는 초까지만 적고 구글은 밀리초까지 주므로, 그대로 두면 같은 초에 고친 로컬 수정이 조용히 되돌려진다.
- 동점이면 로컬이 이긴다.
- 폰의 완료를 받다가 로컬 규칙(하위할일 미완료 등)에 막히면 **건너뛰고 보고**한다. 로컬 규칙이 이긴다.
- 폰에는 `todo`/`doing` 구분이 없다. 폰에서 완료를 풀면 `doing` 이었어도 `todo` 로 내려온다.

### 삭제

`meta.gtasks_seen_ids` 에 지난 회차의 태스크 id 를 남겨 두는 것이 "폰에서 새로 만든 것"과 "로컬에서 지운 것"을 가르는 유일한 근거다.

| 상황 | 처리 |
| --- | --- |
| 대시보드에서 지움 | 구글에서도 지움 |
| 폰에서 지움 (미완료) | 되살림 — 존재 여부는 대시보드가 정한다 |
| 폰에서 지움 (완료) | 그대로 둠 — '완료 항목 삭제'가 무덤을 파헤치면 안 되므로 |

## 규칙 몇 가지

- 우선순위는 워크스페이스 순위 + 할일 순서로만 표현한다. **할일은 중요도가 아니라 착수 가능한 순서로 놓는다.**
- 카테고리는 그룹핑 분류일 뿐 우선순위 계산에 관여하지 않는다.
- 카테고리 삭제는 워크스페이스·할일이 없을 때만(있으면 먼저 옮긴다). 분류된 세션만 남아 있으면 몇 건인지 알리고 확인을 받은 뒤(`DELETE /api/categories/<id>?force=1`) 그 세션들을 미분류로 내리고 지운다. 붙은 게 아무것도 없으면 되묻지 않는다.
- 워크스페이스 삭제 시 소속 할일은 미분류로 내려간다. 할일 삭제는 하위할일까지 지운다.
- 웹과 CLI가 같은 DB를 쓴다. CLI 변경을 웹에서 보려면 새로고침한다. 세션 영역만 2초 폴링한다.
- 마크다운은 루트 `.markdownlint.json` 을 따른다. 표 구분행은 `| --- | --- |`, 코드펜스에는 언어를 붙인다(`text`, `bash`, `json` 등).

## 디자인 토큰

`static/css/app.css` 의 `:root` 가 유일한 출처다. `usage.css` 는 정의하지 않고 참조만 한다.
**font-size·padding·margin·gap·border-radius 에 생 px 을 쓰지 않는다** — `tests/test_css_tokens.py` 가 어기면 실패시킨다. width·height·box-shadow 같은 그래픽 치수(점·바 두께)는 격자와 무관하므로 예외.

| 종류 | 토큰 | 값 | 쓰는 곳 |
| --- | --- | --- | --- |
| 간격 | `--sp-2` ~ `--sp-48` | 2 / 4 / 8 / 12 / 16 / 20 / 24 / 32 / 40 / 48 | 4px 격자. `--sp-2` 만 반 칸. 6·9·10·11·14 같은 사이값은 쓰지 않는다 |
| 간격 별칭 | `--gap`, `--pad-card` | 둘 다 16px | 카드 사이 간격 / 카드 내부 여백. 카드 안 헤더·행은 `--sp-12` |
| 글자 | `--fs-display` | 32px | 카드 하나를 대표하는 큰 수치 |
| | `--fs-title` | 20px | 화면 제목 |
| | `--fs-body` | 13px | 본문. 카드 제목은 같은 크기에 700 |
| | `--fs-sm` | 11px | 보조 본문·라벨·메타·캡션·표·컨트롤 |
| | `--fs-micro` | 9px | 배지·칩·차트 눈금 |
| 행간 | `--lh-tight` / `--lh-heading` / `--lh-body` | 1.1 / 1.3 / 1.55 | 큰 수치 / 제목·배지 / 본문 |
| 둥글기 | `--r-card` / `--r-ctl` / `--r-pill` | 12 / 8 / 999px | 카드 / 컨트롤·중첩 카드 / 알약·점 |
| 그 외 | `--icon-box` | 24px | 16px 아이콘을 담는 정사각 면 |

새 요소를 만들 때의 판단 기준:

- 보조 글자를 나눈 기준 — 글로 읽는 것(캡션·메타·표)은 `--fs-sm`, 배지·칩·눈금은 `--fs-micro`
- 굵기는 400(본문)·500(라벨·보조)·600(강조·세션 이름)·700(카드 제목·큰 수치) 네 단만
- 라벨은 어디서든 `--fs-sm` + 500 + `--muted`, 카드 제목은 `--fs-body` + 700
- 초점 링은 app.css 의 전역 `:focus-visible` 하나가 그린다. 요소마다 따로 정의하지 않는다 (입력 필드만 `:focus` 링을 따로 갖는다)
- 아이콘↔글자 간격은 `--sp-8`, 칩·배지 내부는 `--sp-4`
- 차트 글자만 예외로 `static/js/chart.js` 의 `AXIS_FONT`(11 = `--fs-micro`), `DONUT_TOTAL_FONT`(20 = `--fs-title`) 가 정한다. SVG 좌표 계산에 쓰이기 때문

## 세션 연동 (②)

코드·훅 등록 모두 적용됨 (2026-07-30 확인). 남은 항목은 `docs/superpowers/specs/2026-07-30-session-mapping-spec.md` 에 결정으로 적혀 있다 (세션 인자 env 폴백, fork 세션 분류 상속).

보드의 세션 줄과 할일 줄은 **같은 팝업**을 연다. 팝업은 탭 두 개다.

| 탭 | 내용 | 기본 활성 |
|---|---|---|
| 개요 | 할일 제목, 생성·수정·완료 시각(최근 순), note 전문 | 할일에서 열 때 |
| 세션 | 세션 id·위치·최근 대화 10건, 워크스페이스·카테고리 지정 | 세션에서 열 때 |

세션에서 열면 개요 탭에 그 세션이 `link-todo` 로 잡은 할일이 뜨고, 할일에서 열면 세션 탭에 그 할일을 마지막으로 잡은 세션이 뜬다. note 는 세션에 `(컨텍스트 #id)` 표시만 주입되므로 전문을 보는 자리는 이 팝업이다. 최근 대화는 `~/.claude/projects/*/<세션id>.jsonl` 꼬리에서 읽는다.

### 다른 PC 에 옮길 때

`hooks/dash_hook.py` 의 **절대 경로**가 필요하다. 워크트리에서 쓰고 있다면 워크트리가 지워질 때 훅이 깨지므로 영구 경로에 둔 뒤 등록한다.

`~/.claude/settings.json` 백업 후 네 이벤트에 각각 추가한다(마지막 인자만 이벤트명으로 바꿈).

```json
{"hooks": [{"type": "command", "command": "python3 <절대경로>/hooks/dash_hook.py SessionStart", "timeout": 2}]}
```

같은 작업에서 `hooks.SessionStart` 의 `bash ~/.claude/skills/scope-guard/session-inject.sh` 항목을 **제거**한다. 남겨두면 같은 내용이 두 번 주입된다.

### scope-guard 흡수 (적용 완료)

`~/.claude/skills/scope-guard/scope_db.py` 가 `app/services/session_link.py` 의 `scope_guard_block()` 을 쓰는 dash.db 어댑터로 교체돼 있고(`scope_db.py.bak` 보존), `session-inject.sh` 훅은 `settings.json` 에서 제거됐다. 목표·하위단계는 대시보드의 워크스페이스·할일이다. 흡수 범위를 여기서 끝내는 근거는 ② 스펙 D4 참고.

**주의** — `scope_db.py set-steps` 는 워크스페이스의 할일을 전부 지우고 다시 넣는다. 할일에 하위할일·컨텍스트 노트가 붙은 워크스페이스에서는 실행하지 말 것.

### 롤백

훅 등록 후 문제가 생기면:

```bash
cp ~/.claude/settings.json.bak ~/.claude/settings.json
cp ~/.claude/skills/scope-guard/scope_db.py.bak ~/.claude/skills/scope-guard/scope_db.py
cp ~/.claude/scope-guard/scope.db.bak ~/.claude/scope-guard/scope.db
```

## 설계 문서

| 단계 | 문서 | 상태 |
| --- | --- | --- |
| ① 4계층 + 웹/CLI | `specs/2026-07-29-work-dashboard-design.md`, `plans/2026-07-29-work-dashboard.md` | 구현 완료 |
| ② 세션 매핑 | `specs/2026-07-29-session-link-design.md` (설계) + `specs/2026-07-30-session-mapping-spec.md` (확정 결정) | 대부분 구현, 잔여 2건 |
| ③ 결정 대기 큐 | `specs/2026-07-30-decision-queue-spec.md` | 결정 확정, 미구현 |
| ④ 자율 실행 | `specs/2026-07-30-autorun-spec.md` | 결정 확정, 미구현 |
| ⑤ 초기 설정(온보딩) | `specs/2026-08-01-onboarding-spec.md` | 구현 완료 |

경로는 모두 `docs/superpowers/` 기준. ②③④ 문서는 각각 (a) 문제 (b) 확정 결정과 근거 (c) 안 하는 것 (d) 파일 경계를 담고 있어 그대로 착수할 수 있다.

## 아직 없는 것

- 결정 대기 큐 (③), 자율 실행 (④) — 스펙만 있고 코드 없음
- 완료 항목 아카이브, 할일 의존성, 카테고리 우선순위
