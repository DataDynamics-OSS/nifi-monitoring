# shellcheck shell=bash
# bin/*.sh가 읽는 실행 환경입니다(셸 문법). 비밀번호를 넣는다면 chmod 600으로 둡니다.

# Python 3.9 이상입니다. pip·venv는 필요 없습니다(src/·lib/를 그대로 씁니다)
PYTHON=python3

# 인자 없이 또는 all로 실행할 서비스입니다: exporter provenance relay
#   exporter    config/nifi-exporter.yaml     (9103)
#   provenance  config/provenance-query.yaml  (9104, 선택)
#   relay       config/alert-relay.yaml       (9105, 선택)
SERVICES="exporter"

STOP_TIMEOUT=30 # 정상 종료를 기다리는 시간(초)입니다. 넘으면 강제 종료합니다
START_WAIT=10   # 시작 후 /healthz 응답을 기다리는 시간(초)입니다
ALLOW_ROOT=no   # root 실행을 허용하려면 yes로 둡니다

# 비밀값은 config/secrets/의 파일(password_file)을 권장합니다. 환경변수로 줄 때만 씁니다
# export NIFI_PASSWORD=...
# export NIFI_EXPORTER_BASIC_AUTH_PASSWORD=...
# export NIFI_ALERT_RELAY_PASSWORD=...
# export OPS_API_TOKEN=...   # alert-relay.yaml의 ${OPS_API_TOKEN}
