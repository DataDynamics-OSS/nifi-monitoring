#!/bin/sh
# authorizers.xml에 두 노드 identity를 넣은 뒤 이미지의 start.sh를 실행합니다.
# start.sh/secure.sh는 "Initial User Identity 1"(관리자)과 "Node Identity 1"만 채우지만,
# 2노드 클러스터에서는 모든 노드가 사용자이자 노드 identity로 등록되어야 합니다.
set -e
conf=/opt/nifi/nifi-current/conf/authorizers.xml
if ! grep -q '<property name="Node Identity B">' "$conf"; then
    sed -i \
        -e 's|\(<property name="Initial User Identity 1"></property>\)|\1\n        <property name="Initial User Identity A">CN=nifi-1</property>\n        <property name="Initial User Identity B">CN=nifi-2</property>|' \
        -e 's|\(<property name="Node Identity 1"></property>\)|\1\n        <property name="Node Identity A">CN=nifi-1</property>\n        <property name="Node Identity B">CN=nifi-2</property>|' \
        "$conf"
fi
# 선택 사항: content 아카이브를 끕니다. 아카이브가 켜져 있으면 NiFi가 아카이브 한도(90%)에서
# 쓰기를 막고 해제된 내용을 몇 시간 보관하므로, nifi-2의 작은 tmpfs에서는 디스크 알림
# (80% / 92%)이 발화하지도 해소되지도 않습니다.
if [ "${NIFI_CONTENT_ARCHIVE_ENABLED:-}" = "false" ]; then
    sed -i "s|^nifi.content.repository.archive.enabled=.*|nifi.content.repository.archive.enabled=false|" \
        /opt/nifi/nifi-current/conf/nifi.properties
fi
exec /opt/nifi/scripts/start.sh
