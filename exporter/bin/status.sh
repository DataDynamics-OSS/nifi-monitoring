#!/usr/bin/env bash
# 서비스 상태를 봅니다.
#
#   bin/status.sh                      config/env.sh의 SERVICES (기본 exporter)
#   bin/status.sh all                  SERVICES 전체, 또는 exporter | provenance | relay
#
# 출력 예: exporter  RUNNING  pid=1234 uptime=03:12:45 listen=0.0.0.0:9103 healthz=ok log=logs/...
# 종료 코드: 0 모두 정상, 1 실행 중이지만 /healthz 실패, 3 멈춘 서비스가 있음
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

require_python
rc=0
for svc in $(resolve_services "$@"); do
  if ! pid=$(running_pid "$svc"); then
    printf '%-10s STOPPED\n' "$svc"
    rc=3
    continue
  fi
  uptime=$(ps -o etime= -p "$pid" 2>/dev/null | tr -d ' ')
  if info=$(config_info "$svc" 2>/dev/null); then
    listen=${info% *}
    log_file=${info#* }
    [ "$log_file" = - ] && log_file=$(out_file "$svc")
    if healthz "$listen"; then
      health=ok
    else
      health=fail
      [ $rc = 0 ] && rc=1
    fi
  else
    listen=?
    log_file=?
    health="unknown(설정 파일을 읽지 못했습니다)"
    [ $rc = 0 ] && rc=1
  fi
  printf '%-10s RUNNING  pid=%s uptime=%s listen=%s healthz=%s log=%s\n' \
    "$svc" "$pid" "$uptime" "$listen" "$health" "$log_file"
done
exit $rc
