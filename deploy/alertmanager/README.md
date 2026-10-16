# NiFi 모니터링용 Alertmanager

| 파일 | 용도 |
|---|---|
| `alertmanager.yml` | 라우팅(모든 알림 → 알림 중계 `custom-relay`, critical → 호출기 + Slack, warning → Slack, exporter → 플랫폼팀), 억제 규칙 |
| `templates/nifi.tmpl` | 알림의 `summary`/`description` annotation을 쓰는 Slack 제목·본문 템플릿 |

`custom-relay`는 `nifi-alert-relay`(exporter 이미지의 진입점)로 보내는 webhook 수신처입니다. 중계 서비스가 설정한 대상마다 필터·본문 템플릿을 적용해 사용자 정의 HTTP API로 다시 보냅니다(루트 README 4.7, `exporter/config/nifi-alert-relay.example.yaml`). 쓰지 않으면 이 수신처와 맨 앞 route를 지웁니다. 비밀번호는 `/etc/alertmanager/alert_relay_password` 파일에 둡니다.

## 검증

```bash
cd deploy/alertmanager
amtool check-config alertmanager.yml
```

## 비밀값

`slack_api_url_file`과 `smtp_auth_password_file`은 실행 시점에 마운트하는 파일을 가리킵니다.
웹훅 URL이나 SMTP 비밀번호를 이 YAML에 직접 넣지 않습니다.

## 억제 요약

| 이 알림이 발화하면 | 이 알림들이 억제됩니다 | 범위 |
|---|---|---|
| `NiFiExporterDown`, `NiFiCollectorFailing` | exporter 외의 모든 알림 | 같은 `cluster` |
| `NiFiNodeDisconnected` | 큐 / Processor / Bulletin 알림 | 같은 `cluster` |
| `NiFiClusterQuorumLost` | 노드별 단절 / heartbeat 알림 | 같은 `cluster` |
| `NiFiQueueBackpressureEngaged` | 80%, 증가, 정체 경고 | 같은 `connection_id` |
| `NiFiHeapCritical` | `NiFiHeapHigh`, `NiFiGCTimeHigh` | 같은 `node_id` |
| `NiFiRepositoryDiskCritical` | `NiFiRepositoryDiskHigh` | 같은 저장소 |
| `NiFiCollectorFailing` | `NiFiCollectorStale` | 같은 `cluster`, `collector` |

`equal: [cluster]`가 동작하려면 `up{job="nifi-exporter"}`에 `cluster` 레이블이 있어야 합니다.
`prometheus.yml`은 `nifi-exporter` 스크레이프 job에 이 레이블을 붙이고, `honor_labels: true`로 exporter가
노출하는 메트릭에서는 exporter 자신의 `cluster` 레이블이 우선하게 합니다.
