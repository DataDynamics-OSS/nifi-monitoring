# NiFi 모니터링용 Prometheus

| 파일 | 용도 |
|---|---|
| `prometheus.yml` | 스크레이프 job: `nifi-exporter`(주 경로), `nifi-builtin`(노드별 NiFi 엔드포인트, mTLS 또는 TLS 없는 HTTP), `node`(선택, node_exporter), `nifi-alert-relay`(알림 중계 서비스) |
| `rules/nifi-recording.yml` | 대시보드와 알림이 쓰는 recording rule 31개 (`nifi:<metric>:<op>`) |
| `rules/nifi-alerts.yml` | 알림 규칙 24개 (severity critical/warning, 라우팅용 component 레이블). 알림 중계 장애 2개 포함 |
| `tests/*_test.yml` | recording rule과 알림 규칙의 promtool 단위 테스트 |

## 검증

```bash
cd deploy/prometheus
promtool check config --syntax-only prometheus.yml   # TLS 파일이 있는 환경에서는 --syntax-only를 뺍니다
promtool check rules rules/*.yml
promtool test rules tests/*_test.yml
```

## 참고

- exporter는 모든 메트릭에 `cluster` 레이블을 붙입니다. 다른 출처의 스크레이프 job(`nifi-builtin`, `node`)도
  `static_configs.labels`에 같은 값을 지정해야 조인과 대시보드가 맞아떨어집니다.
- `nifi-builtin`은 클라이언트 인증서 인증에서만 동작합니다. Prometheus는 NiFi bearer 토큰을 갱신할 수 없기
  때문입니다. bearer 인증을 쓰면 이 job을 지웁니다. 그러면 `nifi-recording-builtin` 규칙은 시계열을 만들지
  않을 뿐입니다.
- TLS·인증이 없는 NiFi(HTTP)는 `nifi-builtin`을 `scheme: http`로 바꾸고 `tls_config` 없이 스크레이프합니다
  (`prometheus.yml`의 주석 예시 참고).
- `nifi:thread_pool_utilization`은 노드별 timer-driven 스레드 풀 사용률입니다(`nifi_node_active_threads` /
  `nifi_controller_max_timer_driven_threads`). 단일 노드 NiFi에는 노드별 값이 없어 `nifi_controller_active_threads`로
  계산하고 `node_id="standalone"`을 붙입니다. 90% 이상이 10분 지속되면 `NiFiThreadPoolSaturated`가 발화합니다.
- `*_5m` 메트릭은 5분 롤링 통계(gauge)입니다. 규칙은 큐 적체량에 `delta()`를 쓰고,
  `rate()`/`increase()`는 실제 카운터에만 씁니다. Bulletin의 최근 5분 건수는 첫 수집분도
  반영하는 `nifi_bulletins_observed_5m`을 합산합니다. 기존 `nifi:bulletins_error:increase5m` 이름은 유지합니다.
  이 규칙을 적용하기 전에 새 gauge를 제공하는 exporter를 먼저 배포해야 합니다.
- 클러스터당 exporter는 **1개**만 스크레이프합니다. 2개를 함께 스크레이프하면 모든 `*_info` 시계열이 중복되어
  `group_left` 조인 규칙이 실패하고 알림이 동작하지 않습니다(`NiFiExporterDuplicate`가 발화합니다).
  가용성은 재시작하는 실행 환경과 `NiFiExporterDown`으로 확보합니다.
