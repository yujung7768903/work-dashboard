#!/usr/bin/env bash
# stop.sh·restart.sh 가 source 하는 공용 부분: 이 디렉토리를 cwd 로 돌고 있는
# server.py 를 찾아 멈춘다. 탐지가 두 군데로 갈리면 restart 가 남의 서버를 죽인다.
#
# 프로세스 조회는 /proc 이 있으면(Linux) 그걸로, 없으면(macOS) lsof·ps 로 한다
# — release.py 와 같은 관례. 실행하는 파일이 아니라 source 전용이다.

EXIT_WAIT_TRIES=25 # 0.2초씩 — 포트가 풀리기 전에 새로 띄우면 bind 가 실패한다

serving_pids() {
  local here pid cwd
  here=$(pwd -P) # lsof 는 심볼릭 링크를 푼 경로를 주므로 비교할 쪽도 풀어둔다
  # 인터프리터 이름으로 좁히지 않는다 — python3 가 pyenv 샤임을 거치지 않고 바로
  # 풀리면(예: Xcode CommandLineTools 의 Python) 명령줄에 "python3" 가 안 남는다.
  # cwd 로 이미 좁히므로 server.py 하나로도 충분하다
  for pid in $(pgrep -f 'server\.py' || true); do
    if [ -e "/proc/$pid/cwd" ]; then
      cwd=$(readlink -f "/proc/$pid/cwd" 2>/dev/null || true)
    else
      cwd=$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p')
    fi
    if [ "$cwd" = "$here" ]; then
      echo "$pid"
    fi
  done
}

server_args() {
  # pid → 그 서버가 받은 인자. `... server.py --port 9081` → ` --port 9081`
  local pid=$1 cmd
  if [ -r "/proc/$pid/cmdline" ]; then
    cmd=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  else
    cmd=$(ps -p "$pid" -o command= || true)
  fi
  echo "${cmd#*server.py}"
}

with_port() {
  # 받은 pid 중 `--port <포트>` 로 뜬 것만
  local want=$1 pid
  shift
  for pid in "$@"; do
    case " $(server_args "$pid") " in
    *" --port $want "*) echo "$pid" ;;
    esac
  done
}

stop_serving() {
  # 인자로 받은 pid 들을 멈추고 실제로 죽을 때까지 기다린다
  local pid _try
  for pid in "$@"; do
    if ! kill "$pid" 2>/dev/null; then
      echo "이미 없음 $pid"
      continue
    fi
    echo "종료 $pid"
    for _try in $(seq "$EXIT_WAIT_TRIES"); do
      if ! kill -0 "$pid" 2>/dev/null; then break; fi
      sleep 0.2
    done
  done
}
