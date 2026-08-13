#!/usr/bin/env bash
# 대시보드 서버를 백그라운드로 띄운다. 인자는 server.py 로 그대로 넘어간다 (--port, --host).
#   ./start.sh              → 9080
#   ./start.sh --port 9081  → 워크트리용 다른 포트
# 멈추는 것은 ./stop.sh, 같은 인자로 다시 띄우는 것은 ./restart.sh.
# 로그는 logs/YYYY-MM-DD.log 에 이어 쌓고, 7일 넘게 안 쓴 로그는 지운다.
set -euo pipefail
cd "$(dirname "$0")"

LOG_KEEP_DAYS=7

mkdir -p logs
# ponytail: mtime 기준. 아직 쓰이고 있는 로그(오래 떠 있는 서버)는 mtime 이 갱신돼 남는다
find logs -maxdepth 1 -name '*.log' -mtime "+$LOG_KEEP_DAYS" -delete

log="logs/$(date +%F).log"
: >>"$log"
before=$(wc -l <"$log")

# -u 가 아니라 환경변수로 버퍼링을 끈다 — 명령 앞 두 토큰이 'python3 -u' 가 되면
# release.py·worktrees.py 의 서버 탐지가 server.py 를 못 알아본다
PYTHONUNBUFFERED=1 nohup python3 server.py "$@" >>"$log" 2>&1 &
pid=$!

# 뜨면 URL 한 줄, 실패하면 사유를 로그에 남긴다. 그 줄이 나올 때까지만 기다린다
for _ in $(seq 20); do
  if [ "$(wc -l <"$log")" -gt "$before" ]; then break; fi
  if ! kill -0 "$pid" 2>/dev/null; then break; fi
  sleep 0.2
done

tail -n "+$((before + 1))" "$log"
echo "pid $pid · 로그 $log"
