# shellcheck shell=bash
# bin/*.sh가 source하는 공통 함수입니다. 직접 실행하지 않습니다.
#
# 설치(pip·venv) 없이 src/(nifi_exporter)와 lib/(의존 라이브러리)를 PYTHONPATH로 지정해
# 실행합니다. python은 -S로 띄워 시스템 site-packages를 읽지 않으므로 서버에 다른 버전의 httpx 등이 있어도 섞이지 않습니다.
set -u

EXPORTER_HOME=$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
# 설정 파일의 상대 경로(config/secrets/..., logs/...)는 EXPORTER_HOME 기준입니다
cd "$EXPORTER_HOME" || exit 1

# 기본값입니다. config/env.sh가 덮어씁니다
PYTHON=python3
SERVICES=exporter
STOP_TIMEOUT=30
START_WAIT=10
ALLOW_ROOT=no
# shellcheck source=/dev/null
[ -f config/env.sh ] && . config/env.sh

export PYTHONPATH="$EXPORTER_HOME/src:$EXPORTER_HOME/lib"
export PYTHONDONTWRITEBYTECODE=1

die() {
  echo "$*" >&2
  exit 1
}

py() { "$PYTHON" -S "$@"; }

require_python() {
  command -v "$PYTHON" >/dev/null 2>&1 || die "Python을 찾을 수 없습니다: $PYTHON (config/env.sh의 PYTHON)"
  py -c 'import sys; sys.exit(sys.version_info < (3, 11))' ||
    die "Python 3.11 이상이 필요합니다: $("$PYTHON" -V 2>&1) (config/env.sh의 PYTHON)"
  [ -d src/nifi_exporter ] || die "src/nifi_exporter가 없습니다: $EXPORTER_HOME/src"
  py -c 'import httpx, prometheus_client, yaml' 2>/dev/null ||
    die "lib/에 의존 라이브러리가 없습니다: $EXPORTER_HOME/lib (소스 디렉토리에서는 make lib)"
}

require_user() {
  if [ "$(id -u)" = 0 ] && [ "$ALLOW_ROOT" != yes ]; then
    die "root로 실행하지 않습니다. 실행 계정으로 바꾸거나 config/env.sh에서 ALLOW_ROOT=yes로 둡니다"
  fi
}

service_module() {
  case $1 in
    exporter) echo nifi_exporter ;;
    provenance) echo nifi_exporter.provenance ;;
    relay) echo nifi_exporter.alert_relay ;;
    *) return 1 ;;
  esac
}

service_config() {
  case $1 in
    exporter) echo "$EXPORTER_HOME/config/nifi-exporter.yaml" ;;
    provenance) echo "$EXPORTER_HOME/config/provenance-query.yaml" ;;
    relay) echo "$EXPORTER_HOME/config/alert-relay.yaml" ;;
  esac
}

pid_file() { echo "$EXPORTER_HOME/logs/$1.pid"; }

# stdout/stderr입니다. log_file을 지정하면 시작 실패·트레이스백만 남습니다
out_file() { echo "$EXPORTER_HOME/logs/$1.out"; }

# 인자로 받은 서비스 이름을 검사해 출력합니다. 인자가 없거나 all이면 SERVICES를 씁니다.
resolve_services() {
  local list="$*" s
  if [ -z "$list" ] || [ "$list" = all ]; then list=$SERVICES; fi
  for s in $list; do
    service_module "$s" >/dev/null || die "알 수 없는 서비스입니다: $s (exporter | provenance | relay | all)"
  done
  echo "$list"
}

# 실행 중이면 pid를 출력하고 0을 돌려줍니다. pid가 재사용되어 다른 프로세스를 가리키면
# (명령행에 이 서비스의 모듈과 설정 파일이 없으면) 남은 pid 파일로 보고 지웁니다.
running_pid() {
  local svc=$1 f pid args
  f=$(pid_file "$svc")
  [ -f "$f" ] || return 1
  pid=$(cat "$f" 2>/dev/null)
  case $pid in '' | *[!0-9]*)
    rm -f "$f"
    return 1
    ;;
  esac
  if [ -r "/proc/$pid/cmdline" ]; then
    args=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  else
    args=$(ps -ww -o args= -p "$pid" 2>/dev/null)
  fi
  case $args in
    *"-m $(service_module "$svc") --config $(service_config "$svc")"*)
      echo "$pid"
      return 0
      ;;
  esac
  rm -f "$f"
  return 1
}

# 설정 파일에서 "listen log_file"을 읽어 출력합니다(환경변수 덮어쓰기 반영, log_file이 없으면 -).
config_info() {
  py - "$1" "$(service_config "$1")" <<'PY'
import sys

svc, path = sys.argv[1], sys.argv[2]
if svc == "relay":
    from nifi_exporter.alert_relay import load_config

    c = load_config(path)
    listen, log_file = c.listen, c.log_file
else:
    from nifi_exporter import config

    c = config.load(path)
    listen = c.provenance.listen if svc == "provenance" else c.server.listen
    log_file = c.server.log_file
print(listen, log_file or "-")
PY
}

# listen 주소의 /healthz가 200이면 0입니다. 0.0.0.0 등 모든 주소면 127.0.0.1로 부릅니다.
healthz() {
  local host=${1%:*} port=${1##*:}
  case $host in '' | 0.0.0.0 | '[::]' | :: | '*') host=127.0.0.1 ;; esac
  py - "http://$host:$port/healthz" <<'PY'
import sys
import urllib.request

opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # http_proxy를 타지 않습니다
try:
    sys.exit(0 if opener.open(sys.argv[1], timeout=3).status == 200 else 1)
except Exception:
    sys.exit(1)
PY
}
