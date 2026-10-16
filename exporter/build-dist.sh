#!/usr/bin/env bash
# 설치(pip·venv) 없이 bin/ 스크립트로 실행하는 배포 묶음을 만듭니다.
#
#   ./build-dist.sh                       → dist/nifi-exporter-<버전>.tar.gz
#   PYTHON=python3.11 ./build-dist.sh     빌드에 쓸 Python
#   PIP_ARGS="--no-index --find-links wheels" ./build-dist.sh   내려받은 wheel로 빌드
#
# 의존 라이브러리는 빌드 Python 기준으로 고릅니다(예: typing_extensions는 3.13 미만에서만
# 들어갑니다). 빌드 Python은 실행 서버의 Python보다 높지 않게, 되도록 3.11로 둡니다.
# 구성: bin/ config/ logs/ src/ lib/ (README "스크립트 실행" 참고)
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
NAME=nifi-exporter-$VERSION
STAGE=dist/$NAME

rm -rf "$STAGE" "dist/$NAME.tar.gz"
mkdir -p "$STAGE"/{bin,config/secrets,logs,src,lib}

# 의존 라이브러리만 lib/에 담습니다(nifi_exporter 자신은 src/를 그대로 복사합니다)
DEPS=$("$PYTHON" -c 'import tomllib; print(*tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"])')
# DEPS·PIP_ARGS는 여러 인자로 나뉘어야 하므로 따옴표 없이 넘깁니다
# shellcheck disable=SC2086
"$PYTHON" -m pip install --quiet --disable-pip-version-check --no-compile --no-cache-dir \
  --target "$STAGE/lib" ${PIP_ARGS:-} $DEPS
rm -rf "$STAGE/lib/bin" # pip가 만든 실행 파일은 venv 경로를 가리키므로 쓰지 않습니다
tar -C src --exclude=__pycache__ -cf - nifi_exporter | tar -C "$STAGE/src" -xf -
echo "nifi-exporter $VERSION built $(date '+%Y-%m-%dT%H:%M:%S%z')" \
  "with $("$PYTHON" -V 2>&1) ($(uname -m))" >"$STAGE/VERSION"

install -m 755 bin/*.sh "$STAGE/bin/"
install -m 600 config/env.sh "$STAGE/config/"
install -m 640 config/provenance-query.yaml "$STAGE/config/"

# 예시 설정의 /etc 경로를 배포 디렉토리 상대 경로로 바꾸고 로그 파일을 켭니다
sed -e 's|/etc/nifi-exporter/|config/secrets/|g' \
  -e 's|# log_file: /var/log/nifi-exporter/nifi-exporter.log|log_file: logs/nifi-exporter.log|' \
  -e 's|^  # log_max_size:|  log_max_size:|' -e 's|^  # log_backups:|  log_backups:|' \
  config/nifi-exporter.example.yaml >"$STAGE/config/nifi-exporter.yaml"
sed -e 's|/etc/nifi-alert-relay/password|config/secrets/alert-relay-password|g' \
  -e 's|/etc/nifi-alert-relay/|config/secrets/|g' \
  -e 's|^# log_file: /var/log/nifi-alert-relay/nifi-alert-relay.log|log_file: logs/nifi-alert-relay.log|' \
  -e 's|^# log_max_size:|log_max_size:|' -e 's|^# log_backups:|log_backups:|' \
  config/nifi-alert-relay.example.yaml >"$STAGE/config/alert-relay.yaml"
chmod 640 "$STAGE/config/nifi-exporter.yaml" "$STAGE/config/alert-relay.yaml"
chmod 700 "$STAGE/config/secrets"
for f in nifi-exporter alert-relay; do
  grep -q '^ *log_file: logs/' "$STAGE/config/$f.yaml" || {
    echo "config/$f.yaml에 log_file을 넣지 못했습니다(예시 설정의 주석이 바뀌었는지 확인합니다)" >&2
    exit 1
  }
  ! grep -q '/etc/' "$STAGE/config/$f.yaml" || {
    echo "config/$f.yaml에 /etc 경로가 남았습니다" >&2
    exit 1
  }
done

tar -C dist --owner=0 --group=0 -czf "dist/$NAME.tar.gz" "$NAME"
echo "dist/$NAME.tar.gz"
