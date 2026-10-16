#!/bin/sh
# TLS와 인증이 없는 단일 노드 NiFi 2.6.0을 띄웁니다(compose 프로필 "plain").
# 이미지의 start.sh는 HTTPS를 강제하므로 nifi.properties를 HTTP로 바꾼 뒤 nifi.sh를 직접
# 실행합니다. 모든 요청은 anonymous 사용자로 처리되며, NiFi는 HTTP에서 토큰을 발급하지
# 않으므로 exporter는 auth.mode: none으로 붙습니다.
set -e
P=/opt/nifi/nifi-current/conf/nifi.properties
sed -i \
    -e 's|^nifi.web.http.host=.*|nifi.web.http.host=0.0.0.0|' \
    -e 's|^nifi.web.http.port=.*|nifi.web.http.port=8080|' \
    -e 's|^nifi.web.https.host=.*|nifi.web.https.host=|' \
    -e 's|^nifi.web.https.port=.*|nifi.web.https.port=|' \
    -e 's|^nifi.security.keystore=.*|nifi.security.keystore=|' \
    -e 's|^nifi.security.keystoreType=.*|nifi.security.keystoreType=|' \
    -e 's|^nifi.security.keystorePasswd=.*|nifi.security.keystorePasswd=|' \
    -e 's|^nifi.security.keyPasswd=.*|nifi.security.keyPasswd=|' \
    -e 's|^nifi.security.truststore=.*|nifi.security.truststore=|' \
    -e 's|^nifi.security.truststoreType=.*|nifi.security.truststoreType=|' \
    -e 's|^nifi.security.truststorePasswd=.*|nifi.security.truststorePasswd=|' \
    -e 's|^nifi.security.user.authorizer=.*|nifi.security.user.authorizer=|' \
    -e 's|^nifi.security.user.login.identity.provider=.*|nifi.security.user.login.identity.provider=|' \
    -e 's|^nifi.remote.input.secure=.*|nifi.remote.input.secure=false|' \
    -e 's|^nifi.sensitive.props.key=.*|nifi.sensitive.props.key=plain-test-sensitive-key|' \
    "$P"
exec /opt/nifi/nifi-current/bin/nifi.sh run
