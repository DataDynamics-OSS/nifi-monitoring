#!/bin/sh
# 이 디렉터리의 로컬 스택에서 쓰는 테스트용 PKI와 비밀값을 만듭니다.
#
#   certs/ca.pem                          CA입니다 (NiFi, exporter, Prometheus가 신뢰합니다)
#   certs/nifi-{1,2}.p12                  노드 키스토어입니다 (서버·클라이언트 인증, SAN nifi-N, localhost, 127.0.0.1)
#   certs/truststore.p12                  NiFi용 CA 트러스트스토어입니다
#   certs/{admin,nifi-monitor,prometheus,nifi-provenance}.{pem,key}  클라이언트 인증서입니다 (CN=<이름>)
#   certs/admin.p12                       브라우저에 등록할 관리자 인증서입니다
#   certs/metrics-password                exporter /metrics basic auth 비밀번호입니다 (사용자 prometheus)
#   certs/alert-relay-password            nifi-alert-relay basic auth 비밀번호입니다 (사용자 alertmanager)
#   certs/slack_webhook, smtp_password    Alertmanager용 더미 비밀값입니다
#
# 비밀번호는 고정된 테스트 값이므로 로컬 테스트 외에는 절대 쓰지 않습니다.
# 이미 있는 파일은 유지합니다. 전부 다시 만들려면 certs/를 지웁니다.
set -eu

cd "$(dirname "$0")"
OUT=certs
PASS=localtest
NIFI_IMAGE=${NIFI_IMAGE:-apache/nifi:2.6.0}
mkdir -p "$OUT"

if [ ! -f "$OUT/ca.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 825 -subj "/CN=nifi-local-ca" \
        -keyout "$OUT/ca.key" -out "$OUT/ca.pem" 2>/dev/null
fi

issue() { # 인자: 이름, 확장 필드입니다
    [ -f "$OUT/$1.pem" ] && return 0
    openssl req -newkey rsa:2048 -nodes -subj "/CN=$1" \
        -keyout "$OUT/$1.key" -out "$OUT/$1.csr" 2>/dev/null
    printf '%s\n' "$2" > "$OUT/$1.ext"
    openssl x509 -req -in "$OUT/$1.csr" -CA "$OUT/ca.pem" -CAkey "$OUT/ca.key" \
        -CAcreateserial -days 825 -extfile "$OUT/$1.ext" -out "$OUT/$1.pem" 2>/dev/null
    rm -f "$OUT/$1.csr" "$OUT/$1.ext"
}

for n in nifi-1 nifi-2; do
    issue "$n" "subjectAltName=DNS:$n,DNS:localhost,IP:127.0.0.1
extendedKeyUsage=serverAuth,clientAuth"
    [ -f "$OUT/$n.p12" ] || openssl pkcs12 -export -name "$n" -inkey "$OUT/$n.key" \
        -in "$OUT/$n.pem" -certfile "$OUT/ca.pem" -passout "pass:$PASS" -out "$OUT/$n.p12"
done
for u in admin nifi-monitor prometheus nifi-provenance; do
    issue "$u" "extendedKeyUsage=clientAuth"
done
[ -f "$OUT/admin.p12" ] || openssl pkcs12 -export -name admin -inkey "$OUT/admin.key" \
    -in "$OUT/admin.pem" -passout "pass:$PASS" -out "$OUT/admin.p12"

# Java 트러스트스토어(trustedCertEntry)에는 keytool이 필요하므로 NiFi 이미지의 것을 빌려 씁니다.
if [ ! -f "$OUT/truststore.p12" ]; then
    docker run --rm -u "$(id -u):$(id -g)" -v "$PWD/$OUT:/certs" --entrypoint keytool \
        "$NIFI_IMAGE" -importcert -noprompt -alias ca -file /certs/ca.pem \
        -keystore /certs/truststore.p12 -storetype PKCS12 -storepass "$PASS" >/dev/null
fi

[ -f "$OUT/metrics-password" ] || printf '%s\n' "$PASS" > "$OUT/metrics-password"
[ -f "$OUT/alert-relay-password" ] || printf '%s\n' "$PASS" > "$OUT/alert-relay-password"
# Alertmanager 비밀값은 전달될 수 없는 더미이며, 로컬에서는 발송 실패가 정상입니다.
[ -f "$OUT/slack_webhook" ] || printf '%s\n' "http://127.0.0.1:9/slack" > "$OUT/slack_webhook"
[ -f "$OUT/smtp_password" ] || printf '%s\n' "unused" > "$OUT/smtp_password"

chmod 644 "$OUT"/*
echo "certs written to $OUT/ (password: $PASS)"
