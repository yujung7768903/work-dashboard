#!/usr/bin/env bash
# 이 디렉토리에서 돌던 서버를 종료하고 run.sh 로 다시 띄운다.
#   ./restart.sh              → 돌던 서버와 같은 인자(포트)로
#   ./restart.sh --port 9081  → 인자를 주면 그 인자로
# 다른 워크트리·메인 체크아웃의 서버는 cwd 가 달라 건드리지 않는다.
set -euo pipefail
cd "$(dirname "$0")"

EXIT_WAIT_TRIES=25 # 0.2초씩 — 포트가 풀리기 전에 새로 띄우면 bind 가 실패한다

here=$(pwd -P) # lsof 는 심볼릭 링크를 푼 경로를 주므로 비교할 쪽도 풀어둔다
args=("$@")
for pid in $(pgrep -f 'python3 server\.py' || true); do
  # macOS 에는 /proc 이 없다 — cwd·명령줄을 lsof·ps 로 읽는다 (worktrees.py 와 같은 방식)
  cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
  [ "$cwd" = "$here" ] || continue
  # 인자를 안 줬으면 죽는 서버의 인자를 물려받는다 — 포트를 매번 다시 적지 않게
  if [ ${#args[@]} -eq 0 ]; then
    # bash 3.2 에는 mapfile 이 없다. 인자에 공백이 없으니 IFS 분리로 충분하다
    read -r -a old <<<"$(ps -p "$pid" -o command=)"
    args=("${old[@]:2}") # `python3 server.py` 다음부터가 인자
  fi
  kill "$pid"
  echo "종료 $pid"
  for _ in $(seq "$EXIT_WAIT_TRIES"); do
    if ! kill -0 "$pid" 2>/dev/null; then break; fi
    sleep 0.2
  done
done

# bash 3.2 는 set -u 에서 빈 배열의 "${args[@]}" 를 unbound 로 본다
exec ./run.sh ${args[@]+"${args[@]}"}
