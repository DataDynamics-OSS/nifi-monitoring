#!/usr/bin/env bash
# 설정 파일을 검사합니다(서비스는 건드리지 않습니다). 설정을 고친 뒤 restart 전에 씁니다.
#
#   bin/check-config.sh                config/env.sh의 SERVICES (기본 exporter)
#   bin/check-config.sh relay          지정한 서비스 (exporter | provenance | relay | all)
#
# 비밀번호 파일·인증서 경로와 ${ENV} 치환까지 확인합니다. 하나라도 틀리면 종료 코드 1입니다.
# shellcheck source=common.sh
. "$(dirname "$0")/common.sh"

require_python
rc=0
for svc in $(resolve_services "$@"); do
  conf=$(service_config "$svc")
  if [ ! -f "$conf" ]; then
    echo "$svc: 설정 파일이 없습니다: $conf" >&2
    rc=1
  elif py -m "$(service_module "$svc")" --config "$conf" --check-config >/dev/null; then
    info=$(config_info "$svc")
    log_file=${info#* }
    [ "$log_file" = - ] && log_file="(없음, $(out_file "$svc")에 씁니다)"
    echo "$svc: 정상 ($conf, listen ${info% *}, 로그 $log_file)"
  else
    echo "$svc: 오류 ($conf)" >&2
    rc=1
  fi
done
exit $rc
