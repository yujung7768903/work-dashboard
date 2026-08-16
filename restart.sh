#!/usr/bin/env bash
# 이 디렉토리에서 돌던 서버를 종료하고 start.sh 로 다시 띄운다.
#   ./restart.sh              → 돌던 서버와 같은 인자(포트)로
#   ./restart.sh --port 9081  → 인자를 주면 그 인자로, 그 포트로 뜬 것만
# 다른 워크트리·메인 체크아웃의 서버는 cwd 가 달라 건드리지 않는다.
set -euo pipefail
cd "$(dirname "$0")"
. ./serving.sh

args=("$@")
pids=$(serving_pids)
if [ "${1:-}" = "--port" ] && [ -n "${2:-}" ]; then
  pids=$(with_port "$2" $pids)
fi
first=${pids%%$'\n'*}
# 인자를 안 줬으면 죽는 서버의 인자를 물려받는다 — 포트를 매번 다시 적지 않게
if [ ${#args[@]} -eq 0 ] && [ -n "$first" ]; then
  # bash 3.2 에는 mapfile 이 없다. 인자에 공백이 없으니 IFS 분리로 충분하다
  read -r -a args <<<"$(server_args "$first")" || true
fi
stop_serving $pids

# bash 3.2 는 set -u 에서 빈 배열의 "${args[@]}" 를 unbound 로 본다
exec ./start.sh ${args[@]+"${args[@]}"}
