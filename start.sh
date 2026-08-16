#!/usr/bin/env bash
# 대시보드 서버를 백그라운드로 띄운다. 인자는 server.py 로 그대로 넘어간다 (--port, --host).
#   ./start.sh              → 9080, 이 기기에서만
#   ./start.sh --port 9081  → 워크트리용 다른 포트
#   ./start.sh --lan        → 같은 와이파이의 다른 기기(폰·아이패드)에서도 열림
# 멈추는 것은 ./stop.sh, 같은 인자로 다시 띄우는 것은 ./restart.sh.
# 로그는 logs/YYYY-MM-DD.log 에 이어 쌓고, 7일 넘게 안 쓴 로그는 지운다.
set -euo pipefail
cd "$(dirname "$0")"

LOG_KEEP_DAYS=7
ANY_HOST=0.0.0.0
# 어느 인터페이스에서 LAN 주소를 찾을지. 앞의 것부터 — en0 이 보통 무선이다
LAN_INTERFACES="en0 en1"
# 고를 파이썬 후보. 앞의 것부터 — PATH 의 python3 가 되면 그걸 그대로 쓴다
PYTHON_CANDIDATES="python3 /usr/bin/python3 /opt/homebrew/bin/python3"

# ssl 이 되는 python3 를 고른다.
# 표준 라이브러리만 쓰므로 인터프리터를 바꿔도 깨질 것이 없다. 반면 ssl 이 빠진
# 파이썬으로 뜨면 구글 태스크 연동이 HTTPS 를 아예 못 연다 — 같은 3.9 라도
# 빌드에 따라 빠지고(예: pyenv 로 빌드한 뒤 시스템 openssl 이 사라진 경우)
# 그때 urllib 은 "unknown url type: https" 라는, 원인을 짐작할 수 없는 문구로 끝난다
pick_python() {
  local candidate
  for candidate in ${WORK_DASHBOARD_PYTHON:-} $PYTHON_CANDIDATES; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import ssl' >/dev/null 2>&1; then
      echo "$candidate"
      return
    fi
  done
  # 아무것도 없으면 원래대로. 서버는 뜨고 연동만 못 쓴다 — 설정 화면이 사유를 알린다
  echo python3
}

python=$(pick_python)

# --lan 은 server.py 가 모르는 이름이라 여기서 --host 0.0.0.0 으로 바꿔 넘긴다.
# 별칭을 두는 이유는 짧아서가 아니라 주소 때문 — server.py 는 받은 host 를 그대로
# 찍어서 `http://0.0.0.0:9080` 이 나오고, 그건 다른 기기에 붙여넣을 수 없다
lan=""
open_to_lan=""
args=()
for arg in "$@"; do
  if [ "$arg" = "--lan" ]; then
    open_to_lan=1
    args+=(--host "$ANY_HOST")
  else
    # 손으로 준 --host 0.0.0.0 도 같게 본다. restart.sh 는 죽는 서버의 인자를 그대로
    # 물려받아 --lan 이 아니라 이 모양으로 오므로, 플래그 이름만 보면 재실행 때 놓친다
    if [ "$arg" = "$ANY_HOST" ]; then open_to_lan=1; fi
    args+=("$arg")
  fi
done

if [ -n "$open_to_lan" ]; then
  for interface in $LAN_INTERFACES; do
    lan=$(ipconfig getifaddr "$interface" 2>/dev/null || true)
    if [ -n "$lan" ]; then break; fi
  done
fi

mkdir -p logs
# ponytail: mtime 기준. 아직 쓰이고 있는 로그(오래 떠 있는 서버)는 mtime 이 갱신돼 남는다
find logs -maxdepth 1 -name '*.log' -mtime "+$LOG_KEEP_DAYS" -delete

log="logs/$(date +%F).log"
: >>"$log"
before=$(wc -l <"$log")

# -u 가 아니라 환경변수로 버퍼링을 끈다 — 명령 앞 두 토큰이 'python3 -u' 가 되면
# release.py·worktrees.py 의 서버 탐지가 server.py 를 못 알아본다
# bash 3.2 는 set -u 에서 빈 배열의 "${args[@]}" 를 unbound 로 본다 (restart.sh 와 같은 회피)
PYTHONUNBUFFERED=1 nohup "$python" server.py ${args[@]+"${args[@]}"} >>"$log" 2>&1 &
pid=$!

# 뜨면 URL 한 줄, 실패하면 사유를 로그에 남긴다. 그 줄이 나올 때까지만 기다린다
for _ in $(seq 20); do
  if [ "$(wc -l <"$log")" -gt "$before" ]; then break; fi
  if ! kill -0 "$pid" 2>/dev/null; then break; fi
  sleep 0.2
done

started=$(tail -n "+$((before + 1))" "$log")
# 서버가 찍은 0.0.0.0 을 실제 주소로 바꿔 다른 기기에 그대로 붙여넣게 한다.
# 주소를 못 찾았으면 바꾸지 않는다 — 뜬 것은 맞으니 막지 않고 사실만 알린다
if [ -n "$lan" ]; then
  echo "${started//$ANY_HOST/$lan}"
else
  echo "$started"
  if [ -n "$open_to_lan" ]; then
    echo "LAN 주소를 못 찾음($LAN_INTERFACES). 열리기는 했으니 주소는 직접 확인"
  fi
fi
if [ -n "$open_to_lan" ]; then
  echo "LAN 공개 — 인증이 없다. 신뢰하는 와이파이에서만 쓰고, 끝나면 ./stop.sh"
fi
# 인터프리터를 말없이 바꾸면 "왜 다른 파이썬으로 떴지" 를 추적할 길이 없다.
# PATH 의 python3 를 그대로 쓴 흔한 경우에는 굳이 적지 않는다
if [ "$python" != "python3" ]; then
  echo "python3 에 ssl 이 없어 $python 로 띄움 (구글 태스크 연동에 필요)"
fi
echo "pid $pid · 로그 $log"
