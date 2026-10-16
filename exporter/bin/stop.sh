#!/usr/bin/env bash
# 서비스를 멈춥니다.
#
#   bin/stop.sh                        config/env.sh의 SERVICES (기본 exporter)
#   bin/stop.sh exporter relay         지정한 서비스 (exporter | provenance | relay | all)
#
# SIGTERM을 보내고 STOP_TIMEOUT초(기본 30) 기다린 뒤에도 남아 있으면 SIGKILL을 보냅니다.
# 실행 중이 아니면 그대로 성공입니다.
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

stop_one() {
  local svc=$1 pid i
  if ! pid=$(running_pid "$svc"); then
    echo "$svc: 실행 중이 아닙니다"
    return 0
  fi
  kill -TERM "$pid" 2>/dev/null
  for ((i = 0; i < STOP_TIMEOUT; i++)); do
    if ! kill -0 "$pid" 2>/dev/null; then
      rm -f "$(pid_file "$svc")"
      echo "$svc: 멈췄습니다 (pid $pid)"
      return 0
    fi
    sleep 1
  done
  echo "$svc: ${STOP_TIMEOUT}초 안에 끝나지 않아 강제 종료합니다 (pid $pid)" >&2
  kill -KILL "$pid" 2>/dev/null
  rm -f "$(pid_file "$svc")"
  return 0
}

rc=0
for svc in $(resolve_services "$@"); do
  stop_one "$svc" || rc=1
done
exit $rc
