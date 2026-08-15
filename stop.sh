#!/usr/bin/env bash
# 이 디렉토리를 cwd 로 돌던 서버만 멈춘다.
#   ./stop.sh
# 다른 워크트리·메인 체크아웃의 서버는 cwd 가 달라 건드리지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
. ./serving.sh

pids=$(serving_pids)
if [ -z "$pids" ]; then
  echo "이 디렉토리에서 돌고 있는 서버 없음"
  exit 0
fi
stop_serving $pids
