#!/usr/bin/env bash
# 서비스를 백그라운드로 시작합니다.
#
#   bin/start.sh                       config/env.sh의 SERVICES (기본 exporter)
#   bin/start.sh exporter relay        지정한 서비스 (exporter | provenance | relay | all)
#
# 설정을 먼저 검사하고, 띄운 뒤 START_WAIT초 안에 /healthz가 200이면 성공입니다.
# 이미 실행 중이면 그대로 둡니다. 하나라도 실패하면 종료 코드 1입니다.
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

start_one() {
  local svc=$1 module conf pid info listen log_file out i
  module=$(service_module "$svc")
  conf=$(service_config "$svc")
  if pid=$(running_pid "$svc"); then
    echo "$svc: 이미 실행 중입니다 (pid $pid)"
    return 0
  fi
  if [ ! -f "$conf" ]; then
    echo "$svc: 설정 파일이 없습니다: $conf" >&2
    return 1
  fi
  if ! py -m "$module" --config "$conf" --check-config >/dev/null; then
    echo "$svc: 설정 오류로 시작하지 않습니다 ($conf)" >&2
    return 1
  fi
  info=$(config_info "$svc") || return 1
  listen=${info% *}
  log_file=${info#* }
  [ "$log_file" = - ] && log_file=$(out_file "$svc")
  out=$(out_file "$svc")
  # 다른 프로세스가 이미 이 포트에서 응답하면 아래 /healthz 확인이 속으므로 먼저 막습니다
  if healthz "$listen"; then
    echo "$svc: $listen 포트를 이미 다른 프로세스가 쓰고 있습니다. listen을 바꿉니다 ($conf)" >&2
    return 1
  fi

  mkdir -p "$EXPORTER_HOME/logs"
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %z') start $svc" >>"$out"
  # setsid로 터미널 세션에서 떼어 내 터미널을 닫거나 Ctrl-C를 눌러도 함께 죽지 않게 합니다
  if command -v setsid >/dev/null 2>&1; then
    setsid nohup "$PYTHON" -S -m "$module" --config "$conf" >>"$out" 2>&1 </dev/null &
  else
    nohup "$PYTHON" -S -m "$module" --config "$conf" >>"$out" 2>&1 </dev/null &
  fi
  pid=$!
  echo "$pid" >"$(pid_file "$svc")"

  for ((i = 0; i < START_WAIT; i++)); do
    sleep 1
    kill -0 "$pid" 2>/dev/null || break
    if healthz "$listen"; then
      echo "$svc: 시작했습니다 (pid $pid, listen $listen, 로그 $log_file)"
      return 0
    fi
  done
  if kill -0 "$pid" 2>/dev/null; then
    echo "$svc: 프로세스는 실행 중이지만 ${START_WAIT}초 안에 /healthz가 응답하지 않았습니다" \
      "(pid $pid, listen $listen). 로그를 확인합니다: $log_file" >&2
    return 1
  fi
  rm -f "$(pid_file "$svc")"
  echo "$svc: 시작 직후 종료했습니다. $out 마지막 20줄:" >&2
  tail -n 20 "$out" >&2
  [ "$log_file" != "$out" ] && [ -f "$log_file" ] && tail -n 5 "$log_file" >&2
  return 1
}

require_user
require_python
rc=0
for svc in $(resolve_services "$@"); do
  start_one "$svc" || rc=1
done
exit $rc
