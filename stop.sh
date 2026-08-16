#!/usr/bin/env bash
# 이 디렉토리를 cwd 로 돌던 서버만 멈춘다.
#   ./stop.sh              → 이 디렉토리의 서버 전부
#   ./stop.sh --port 9086  → 그중 그 포트를 받은 것만
# 다른 워크트리·메인 체크아웃의 서버는 cwd 가 달라 건드리지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
. ./serving.sh

port=""
if [ "${1:-}" = "--port" ]; then
  port=${2:-}
  if [ -z "$port" ]; then
    echo "--port 뒤에 포트 번호가 필요합니다" >&2
    exit 1
  fi
fi

pids=$(serving_pids)
if [ -n "$port" ]; then
  pids=$(with_port "$port" $pids)
fi
if [ -z "$pids" ]; then
  echo "이 디렉토리에서${port:+ :$port 로} 돌고 있는 서버 없음"
  exit 0
fi
stop_serving $pids
