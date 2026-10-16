#!/usr/bin/env bash
# 서비스를 멈췄다가 다시 시작합니다. 인자는 start.sh·stop.sh와 같습니다.
#
#   bin/restart.sh                     config/env.sh의 SERVICES (기본 exporter)
#   bin/restart.sh relay               지정한 서비스 (exporter | provenance | relay | all)
#
# 설정 파일을 고친 뒤에는 bin/check-config.sh로 먼저 검사합니다. 설정이 틀리면 멈춘 뒤
# 다시 시작하지 못합니다.
BIN=$(dirname "$0")
"$BIN/stop.sh" "$@" || exit 1
exec "$BIN/start.sh" "$@"
