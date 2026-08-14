#!/usr/bin/env bash
# 이 디렉토리에서 돌고 있는 서버의 화면을 png 로 찍는다. 화면을 고쳤으면 이걸로 본다.
#   ./shot.sh                 → /autorun 을 shots/autorun.png 로
#   ./shot.sh board           → /board 를 shots/board.png 로
#   ./shot.sh autorun 1000 700 → 창 크기를 지정 (기본 1400x1000)
#
# 왜 필요한가 — 화면 코드는 DOM 구조 검사(tests/*.mjs)로는 정렬·간격·둥글기가
# 맞는지 알 수 없다. 실제로 baseline 정렬과 카드 둥글기가 어긋난 채 "테스트 통과"
# 로 끝난 적이 있다. 그림 한 장을 근거로 삼는다.
#
# WSL 에서는 리눅스 쪽에 브라우저가 없어도 윈도우에 깔린 Chrome 을 부른다.
# 못 찾으면 리눅스 chrome/chromium 을 찾고, 그것도 없으면 그렇게 알린다.
#
# 한계 — hover·드래그처럼 사람이 만드는 상태는 안 찍힌다. 그건 눈으로 보거나
# 그 상태를 강제하는 CSS 를 잠깐 넣고 찍는다.
set -euo pipefail
cd "$(dirname "$0")"
. ./serving.sh

TAB=${1:-autorun}
WIDTH=${2:-1400}
HEIGHT=${3:-1000}
# 렌더를 기다리는 가상 시간. 안 주면 fetch·언어 로딩 전 빈 화면이 찍힌다
RENDER_BUDGET_MS=8000

pids=$(serving_pids)
if [ -z "$pids" ]; then
  echo "이 디렉토리에서 돌고 있는 서버 없음 — ./start.sh 로 먼저 띄운다" >&2
  exit 1
fi
# 서버가 여럿이면 맨 앞 것. 인자에서 포트를 뽑는다 (없으면 기본 포트)
args=$(server_args "$(echo "$pids" | head -1)")
port=$(echo "$args" | sed -n 's/.*--port[ =]\([0-9]\{1,\}\).*/\1/p')
port=${port:-8765}

find_chrome() {
  local candidate
  for candidate in \
    "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe" \
    "/mnt/c/Program Files (x86)/Google/Chrome/Application/chrome.exe" \
    "/mnt/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"; do
    [ -x "$candidate" ] && echo "$candidate" && return 0
  done
  for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
    command -v "$candidate" >/dev/null 2>&1 && command -v "$candidate" && return 0
  done
  return 1
}

chrome=$(find_chrome) || {
  echo "Chrome 을 못 찾음 — 윈도우 Chrome 도, 리눅스 chromium 도 없다" >&2
  exit 1
}

mkdir -p shots
out="shots/$TAB.png"
# 윈도우 exe 는 윈도우 경로로 써야 한다. 리눅스 브라우저면 그대로 쓴다
case "$chrome" in
/mnt/c/*) target=$(wslpath -w "$(pwd)/$out") ;;
*) target="$(pwd)/$out" ;;
esac

"$chrome" --headless --disable-gpu --hide-scrollbars \
  --window-size="$WIDTH,$HEIGHT" \
  --virtual-time-budget="$RENDER_BUDGET_MS" \
  --screenshot="$target" \
  "http://localhost:$port/$TAB" >/dev/null 2>&1 || true

if [ ! -s "$out" ]; then
  echo "촬영 실패 — 서버(:$port)가 뜬 상태인지 확인한다" >&2
  exit 1
fi
echo "$out · :$port/$TAB · ${WIDTH}x${HEIGHT}"
