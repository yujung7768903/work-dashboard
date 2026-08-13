# 작업 대시보드

Claude Code 세션과 할일을 한 화면에서 잇는 로컬 작업 관리 대시보드

## 요구 사항

- Python 3.9 이상 — 표준 라이브러리만 씀. 의존성 설치는 없고, 하한은 `str.removeprefix` 사용에서 옴
- Claude Code — 세션 연동과 훅이 이 위에서 돎. `~/.claude/` 아래 경로를 읽음
- `claude` CLI (`~/.local/bin/claude`) — 자율 실행과 할일 제목 요약에만 필요
- Node — `static/js` 동작을 검증하는 테스트에만 필요. 없으면 그 테스트만 건너뜀
- `markdownlint-cli2` — `hooks/md_lint.py`를 쓸 때만 필요

## 설치

빌드 단계 없음

```bash
git clone https://github.com/yujung7768903/work-dashboard.git
cd work-dashboard
```

DB 는 첫 실행 때 `~/.claude/work-dashboard/dash.db`에 만들어지고 기본 카테고리가 채워짐

## 실행

```bash
./start.sh
```

주소는 `http://127.0.0.1:9080`. 서버는 백그라운드로 돌고 로그는
`logs/YYYY-MM-DD.log`에 쌓임

| 스크립트 | 하는 일 |
| --- | --- |
| `./start.sh` | 백그라운드 실행. 인자는 `server.py`로 그대로 넘어감 |
| `./stop.sh` | 이 디렉토리를 cwd 로 돌던 서버만 종료 |
| `./restart.sh` | 같은 인자(포트)를 물려받아 다시 실행 |

워크트리에서 동시에 띄울 때는 포트 분리 — `./start.sh --port 9081`

## 사용법

### 화면

왼쪽 레일의 네 탭으로 나뉨

| 탭 | 내용 |
| --- | --- |
| 사용량 | 한도 사용률, 일별 토큰 추이, 지금 돌고 있는 세션 |
| 보드 | 카테고리별 할일 트리(할일 탭)와 저장소·브랜치 목록(워크트리 탭) |
| 워크스페이스 | 배경·목적·목표·고려사항을 담은 카드 그리드 |
| 설정 | 카테고리와 라벨의 이름·색·순서 관리 |

### CLI

같은 DB 를 `dash.py`로도 다룸. `--json`을 붙이면 Claude 가 파싱할 형태로 출력함

```bash
python3 dash.py ls
```

| 명령 | 하는 일 |
| --- | --- |
| `ls` | 카테고리·워크스페이스·할일 트리 개요 |
| `next` | 다음에 할 일 1건 |
| `add-todo <제목>` | 할일 추가. `--note` `--precondition` 으로 컨텍스트 지정 |
| `set-status <대상> <id> <상태>` | 할일·하위할일·워크스페이스 상태 변경 |
| `classify` · `link-todo` | 세션을 카테고리·워크스페이스에 등록하고 할일 연결 |
| `merge` · `finish` | 워크트리 브랜치 병합, 병합 후 리소스 해제 |
| `usage` · `statusline` | 한도 사용률과 토큰 추이, 상태줄 한 줄 |

전체 목록은 `python3 dash.py --help`

### 훅

저장소가 공유하는 등록은 `.claude/settings.json`의 Stop 훅 하나뿐. 나머지는 사용자
설정에 직접 등록해서 쓰고, 이벤트 이름을 인자로 받아 훅 페이로드를 stdin 으로 읽음

| 훅 | 이벤트 | 하는 일 |
| --- | --- | --- |
| `dash_hook.py` | SessionStart · UserPromptSubmit · Stop · SessionEnd | 세션 등록, 상태 갱신, 컨텍스트 주입 |
| `worktree_serve.py` | Stop | 고친 워크트리가 서비스되지 않으면 종료 차단 |
| `worktree_guard.py` | PreToolUse | 메인 체크아웃에서 소스 파일 편집 차단 |
| `commit_scope_guard.py` | PreToolUse | 전체 스테이징·전체 커밋 차단 |
| `stale_base.py` | UserPromptSubmit | 낡은 베이스 위 착수 경고 |
| `md_lint.py` | PostToolUse | 저장된 `.md`를 markdownlint로 검사 |

훅은 전부 fail-open. 훅 자체 오류로 세션이 막히지 않음

### 자율 실행

사람이 자리를 비운 사이 할일 1건씩 `claude --bg` 잡으로 돌림. 대상은 `auto` 라벨이
붙고 착수 조건이 없는 할일뿐이며, 판정은 5분 주기 크론이 부르는 명령이 함

```bash
python3 dash.py autorun-tick --dry-run
```

성공한 잡은 done 이 아니라 검토 대기로 남음. 사람이 배지를 눌러 확인해야 완료로 내려감

## 디렉토리 구조

```text
work-dashboard/
│
├── app/                  # 도메인 계층. 화면과 CLI 가 함께 씀
│   ├── repositories/     # sqlite 읽기·쓰기
│   ├── services/         # 여러 엔티티에 걸친 판정과 조립
│   ├── db.py             # 연결과 스키마
│   └── constants.py      # 매직넘버 모음
│
├── static/               # 화면. 빌드 단계 없는 정적 파일
│   ├── css/
│   └── js/               # 탭별 렌더 모듈
│
├── hooks/                # Claude Code 훅 진입점
│
├── tests/                # 테스트. `.mjs`는 node 로 도는 화면 검증
│
├── docs/                 # 판단 기준과 산출물 예시
│
├── server.py             # HTTP 진입점. 라우팅과 직렬화만 담당
├── dash.py               # CLI 진입점. 파싱과 출력만 담당
└── start.sh              # 실행 스크립트 (stop.sh · restart.sh 와 한 벌)
```

## 개발

```bash
python3 -m tests
```

`tests/`를 전부 찾아 돌림. 화면 동작은 `.mjs` 검증 파일을 node 로 돌려 결과만 받아옴 —
node 가 없으면 그 항목은 건너뜀

코드를 고친 뒤에는 `./restart.sh`로 다시 띄움. 인자를 안 주면 돌던 서버의 포트를
그대로 물려받음

## 설정

서버 인자는 `--host`와 `--port` 둘뿐이고 기본값은 `127.0.0.1:9080`

| 환경변수 | 기본값 | 용도 |
| --- | --- | --- |
| `WORK_DASHBOARD_DB` | `~/.claude/work-dashboard/dash.db` | DB 파일 경로 |
| `CLAUDE_CODE_SESSION_ID` | 세션이 주입 | CLI 가 자기 세션을 알아내는 값 |
| `ALLOW_MAIN_CHECKOUT` | 없음 | `worktree_guard.py` 차단 해제 |
| `ALLOW_BROAD_COMMIT` | 없음 | `commit_scope_guard.py` 차단 해제 |

사용량 집계는 아래 파일을 읽기만 함. 없으면 그 값을 만들지 않고 미수집으로 남김

- `~/.claude/token-optimizer/rate-limits.json` — 한도 사용률
- `~/.claude/metrics/costs.jsonl` — 토큰과 비용
- `~/.claude.json` — 계정과 플랜 이름. 사용량 키 하나만 꺼냄
- `~/.claude/projects/**/*.jsonl` — 세션 최근 대화와 히스토리 요약
