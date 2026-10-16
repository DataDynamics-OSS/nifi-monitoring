#!/usr/bin/env bash
# build-dist.sh로 만든 묶음을 임시 디렉토리에 풀어 세 서비스의 시작·상태·로그·중지를 확인합니다.
# NiFi 없이 돕니다(/healthz는 NiFi 연결과 관계없이 응답합니다).
#
#   ./build-dist.sh && ./smoke-test.sh [PORT_BASE]   (기본 29100: 29103~29105 사용)
set -euo pipefail
cd "$(dirname "$0")"

VERSION=$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)
TARBALL=$PWD/dist/nifi-exporter-$VERSION.tar.gz
PORT_BASE=${1:-29100}
WORK=$(mktemp -d)
HOME_DIR=$WORK/nifi-exporter-$VERSION
trap 'ALLOW_ROOT=yes "$HOME_DIR/bin/stop.sh" all >/dev/null 2>&1 || true; rm -rf "$WORK"' EXIT

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tar -C "$WORK" -xzf "$TARBALL"
cd "$HOME_DIR"
for d in bin config logs src lib; do [ -d "$d" ] || fail "$d/ 없음"; done

cat >config/nifi-exporter.yaml <<EOF
nifi: { base_url: "http://127.0.0.1:9", cluster_name: smoke, auth: { mode: none } }
server:
  listen: 127.0.0.1:$((PORT_BASE + 3))
  log_file: logs/nifi-exporter.log
EOF
cat >config/provenance-query.yaml <<EOF
nifi: { base_url: "http://127.0.0.1:9", cluster_name: smoke, auth: { mode: none } }
server: { log_file: logs/nifi-provenance-query.log }
provenance: { listen: "127.0.0.1:$((PORT_BASE + 4))" }
EOF
cat >config/alert-relay.yaml <<EOF
listen: 127.0.0.1:$((PORT_BASE + 5))
log_file: logs/nifi-alert-relay.log
targets: [{ name: sink, url: "http://127.0.0.1:9/" }]
EOF
sed -i 's/^SERVICES=.*/SERVICES="exporter provenance relay"/' config/env.sh
echo 'ALLOW_ROOT=yes' >>config/env.sh # CI·컨테이너가 root로 돌 수 있습니다

bin/check-config.sh all
bin/start.sh all
bin/status.sh all
bin/start.sh exporter | grep -q "이미 실행 중" || fail "중복 시작을 막지 않음"

for f in nifi-exporter nifi-provenance-query nifi-alert-relay; do
  grep -q '"level"' "logs/$f.log" || fail "logs/$f.log에 로그가 없음"
done
# 시스템 site-packages 없이 src/·lib/만으로 돈다는 것을 확인합니다
pid=$(cat logs/exporter.pid)
tr '\0' ' ' <"/proc/$pid/cmdline" | grep -q -- " -S -m nifi_exporter " || fail "-S 없이 실행됨"

# 남은 pid 파일(다른 프로세스를 가리키는 pid)은 실행 중으로 보지 않습니다
bin/restart.sh relay
bin/stop.sh provenance
echo $$ >logs/provenance.pid
set +e
bin/status.sh all
rc=$?
set -e
[ $rc = 3 ] || fail "status 종료 코드 $rc (3이어야 함)"
[ ! -f logs/provenance.pid ] || fail "남은 pid 파일을 지우지 않음"

bin/stop.sh all
set +e
bin/status.sh all >/dev/null
rc=$?
set -e
[ $rc = 3 ] || fail "중지 후 status 종료 코드 $rc"
ls logs/*.pid >/dev/null 2>&1 && fail "pid 파일이 남음"
echo "smoke test ok"
