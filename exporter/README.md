# nifi-exporter

Apache NiFi 2.x용 Prometheus exporter입니다. Cloudera Flow Management(CFM) 4.12.0에 포함된 NiFi 2.6.0을 대상으로 합니다. 백그라운드 스레드에서 NiFi REST API를 주기적으로 읽고, 가장 최근 스냅샷을 `/metrics`로 제공합니다.

## 수집 항목

| Collector | NiFi 엔드포인트 | 메트릭 (접두사 `nifi_`) |
|---|---|---|
| `cluster` | `GET /controller/cluster` (404면 `GET /flow/cluster/summary`) | `cluster_clustered`, `cluster_nodes_total`, `cluster_nodes_connected`, `node_info`, `node_connected`, `node_status`, `node_heartbeat_age_seconds`, `node_active_threads`, `node_queued_flowfiles`, `node_queued_bytes` |
| `flow` | `GET /flow/process-groups/root/status?recursive=true` | `pg_info`, `pg_*`, `processor_info`, `processor_run_status`, `processor_running`, `processor_*_5m`, `connection_info`, `connection_queued_*`, `connection_percent_used_*`, `connection_*_5m` |
| `flow` (포트, RPG) | 위와 같은 응답 | `port_info`, `port_run_status`, `port_transmitting`, `port_*_5m`, `rpg_info`, `rpg_transmitting`, `rpg_*_5m` (Funnel은 상태 정보가 없습니다) |
| `topology` | Process Group마다 `GET /flow/process-groups/{id}` (기본 300초 주기) | `connection_endpoints_info` (source/destination id와 종류), `connection_backpressure_{object,bytes}_threshold` |
| `diagnostics` | `GET /system-diagnostics?nodewise=true` | `jvm_heap_{used,committed,max}_bytes`, `jvm_heap_utilization`, `jvm_nonheap_{used,committed}_bytes`, `jvm_threads`, `jvm_daemon_threads`, `jvm_gc_*_total`, `jvm_uptime_seconds`, `system_load_average`, `system_available_processors`, `repo_{used,total,free}_bytes`, `repo_utilization` |
| `controller` | `GET /controller/config`, `GET /flow/status` (기본 30초 주기) | `controller_max_timer_driven_threads` (노드별 timer-driven 스레드 풀 크기), `controller_active_threads`, `controller_terminated_threads` (연결된 노드 합계) |
| `bulletin` | `GET /flow/bulletin-board` (노드별 id 커서, 노드가 `limit`에 걸릴 때만 `after`로 추가 조회) | `bulletins_total`, `bulletins_observed_5m`, `bulletin_last_timestamp_seconds` |

exporter 자체 상태: `nifi_exporter_collector_success{collector}`,
`nifi_exporter_collector_last_success_timestamp_seconds{collector}`,
`nifi_exporter_collector_duration_seconds{collector}`,
`nifi_exporter_collector_interval_seconds{collector}`,
`nifi_exporter_api_requests_total{endpoint,code}`,
`nifi_exporter_api_response_bytes{endpoint}`,
`nifi_exporter_token_expiry_timestamp_seconds`, `nifi_exporter_build_info`.

알아 둘 동작:

- `*_5m` 값은 5분 롤링 통계입니다(NiFi 통계 또는 exporter의 Bulletin 관측 건수). gauge이므로 `rate()`/`increase()`를 적용하지 않습니다.
- 이름, 종류, 경로, 연결 관계는 `*_info` 메트릭(값 1)에만 있습니다. PromQL에서 `* on(cluster, pg_id) group_left(pg_path) nifi_pg_info`처럼 조인해서 씁니다.
- NiFi 2.x 상태 응답은 Connection의 source/destination 이름만 주고 id는 주지 않습니다. 그래서 `topology` collector가 flow 엔드포인트에서 id를 읽습니다. 이 collector를 끄면 "하류가 Running인데 큐가 정체" 알림(`NiFiQueueStalled`)이 동작하지 않습니다.
- collector가 실패하면 그 메트릭은 이전 값으로 고정되지 않고 **노출에서 빠지며**, `nifi_exporter_collector_success`가 0이 됩니다. 그래서 "0"과 "미수집"이 구분됩니다.
- Bulletin 카운터는 시작 시점의 가장 최근 Bulletin부터 셉니다. 재시작해도 예전 Bulletin을 다시 세지 않습니다. 클러스터에서는 Bulletin id가 노드마다 따로 증가하므로 커서를 노드별로 두고, 노드가 재시작하면 그 노드의 커서를 리셋합니다. NiFi는 컴포넌트당 최대 5건을 약 5분만 보관하므로 카운터는 하한값입니다. 메시지 원문은 레이블로 쓰지 않습니다. 원문을 JSON 로그로 남기려면 `server.log_bulletin_messages: true`를 설정합니다.
- `nifi_bulletins_observed_5m`은 마지막 성공 수집 시점까지 최근 5분 동안 exporter가 새로 관측한 건수(gauge)입니다. 새 source의 첫 수집분도 포함하고, 5분이 지나면 빠집니다. 첫 주기의 기존 Bulletin은 누적 카운터와 마찬가지로 제외합니다. 알림·대시보드의 `nifi:bulletins_error:increase5m` 규칙은 이 값을 합산합니다. 누적 카운터의 `increase()`는 첫 샘플 이전의 0이 없어 첫 수집분을 놓치므로 사용하지 않습니다.
- `server.basic_auth`(username과 `password_file` 또는 `NIFI_EXPORTER_BASIC_AUTH_PASSWORD`)는 `/metrics`와 `/`를 보호합니다. `/healthz`와 `/readyz`는 프로브용으로 열어 둡니다.
- 단일 노드(비클러스터) NiFi는 `/controller/cluster`에 404를 줍니다. 이때 `cluster` collector는 `/flow/cluster/summary`로 단일 노드인지 확인해, 단일 노드이면 실패로 보고하지 않고 `nifi_cluster_clustered` 0만 냅니다(클러스터면 1). `clustered`가 true인데 404이면 exporter가 붙은 노드가 클러스터에서 끊긴 것이므로 실패로 보고합니다. 단일 노드의 diagnostics 메트릭은 `node_id="standalone"`입니다.
- 실패한 collector는 주기가 길어도 30초 뒤 다시 시도합니다(예: 300초 주기 `topology`). NiFi 재시작 직후의 실패가 오래 이어져 `NiFiCollectorFailing`이 다른 알림을 억제하는 시간을 줄입니다.
- 노드별 스레드 풀 사용률은 recording rule `nifi:thread_pool_utilization`(`nifi_node_active_threads` / `nifi_controller_max_timer_driven_threads`, 단일 노드는 `nifi_controller_active_threads` 기준)로 계산합니다.
- 클러스터당 exporter는 1개만 운영합니다. 2개를 동시에 스크레이프하면 `*_info` 조인이 모두 실패합니다(루트 README 9.2).

## NiFi 사전 준비

읽기 전용 사용자(예: `nifi-monitor`)에게 `/flow`, `/controller`, `/system`의 **view** 권한과 루트 Process Group의 *view the component* 권한을 줍니다.
인증은 `bearer`(`POST /access/token`, Single User / LDAP / Kerberos, 만료 전 JWT 재발급), `mtls`(클라이언트 인증서), `none` 중에서 고릅니다.
TLS·인증이 없는 NiFi(HTTP)는 `nifi.base_url: http://...`과 `nifi.auth.mode: none`으로 붙습니다. `http://` 주소에는 `none`만 허용합니다(NiFi는 HTTPS에서만 토큰을 발급하고, mtls는 TLS가 필요합니다). `nifi.base_url`은 `http://` 또는 `https://`로 시작해야 합니다. 단일 노드 NiFi도 설정을 바꿀 필요가 없습니다.

## 실행

```bash
cd exporter
uv venv --python 3.11 .venv && uv pip install --python .venv/bin/python -e ".[dev]"
cp config/nifi-exporter.example.yaml config.yaml   # 편집합니다
.venv/bin/nifi-exporter --config config.yaml --check-config
.venv/bin/nifi-exporter --config config.yaml
curl -s localhost:9103/metrics | grep nifi_cluster_nodes
```

인터넷이 차단된(airgap) 환경에서는 `packages/py<버전>/`의 오프라인 wheel로 설치합니다. 대상은 RHEL 9.6 / x86_64이며 Python 3.11(`packages/py3.11/`)과 3.9(`packages/py3.9/`)용을 각각 제공합니다. 자세한 내용은 [packages/README.md](packages/README.md)에 있습니다.

```bash
cd exporter
PKG=packages/py3.11          # Python 3.9면 packages/py3.9, python3.9
python3.11 -m venv .venv && source .venv/bin/activate
pip install --no-index --find-links $PKG/ -r $PKG/requirements.txt   # 의존성만
pip install --no-index --find-links $PKG/ .                          # exporter 본체까지
cp config/nifi-exporter.example.yaml config.yaml   # 편집합니다
nifi-exporter --config config.yaml --check-config
nifi-exporter --config config.yaml
```

환경변수로 덮어쓸 수 있는 값: `NIFI_BASE_URL`, `NIFI_USERNAME`, `NIFI_PASSWORD`,
`NIFI_EXPORTER_LISTEN`, `NIFI_EXPORTER_LOG_LEVEL`, `NIFI_EXPORTER_BASIC_AUTH_PASSWORD`.
설정 키 전체와 기본값은 루트 README 5장에 있습니다.

엔드포인트: `/metrics`, `/healthz`(프로세스 동작 여부), `/readyz`(collector가 한 번이라도 성공하면 200).

Docker: `docker build -t nifi-exporter:0.1.0 .`로 빌드하고 설정 파일을 `/etc/nifi-exporter/config.yaml`에 마운트합니다. 이미지는 비root(uid 65534)로 실행합니다.

## 스크립트 실행 (설치 없이)

`make dist`(= `./build-dist.sh`)는 pip·venv 없이 실행하는 묶음 `dist/nifi-exporter-<버전>.tar.gz`를 만듭니다.
서버에는 Python 3.9 이상만 있으면 됩니다. 스크립트가 `PYTHONPATH=src:lib`, `python -S`로 실행하므로 시스템 site-packages와 섞이지 않습니다.

```
bin/       start.sh stop.sh restart.sh status.sh check-config.sh  [exporter|provenance|relay|all]
config/    env.sh(PYTHON, SERVICES, STOP_TIMEOUT …), nifi-exporter.yaml, provenance-query.yaml, alert-relay.yaml, secrets/
logs/      <서비스>.pid, <서비스>.out(stdout/stderr), yaml의 log_file
src/       nifi_exporter
lib/       의존 라이브러리 (VERSION은 최상위)
```

이 디렉토리(`exporter/`)도 같은 `bin/ config/ src/` 구성입니다. `make lib`로 의존 라이브러리를 `lib/`에 받고 `config/nifi-exporter.yaml`을 만들면 `bin/start.sh`로 바로 실행할 수 있습니다(`lib/`·`logs/`·실제 설정은 `.gitignore`).

로그 파일은 yaml에서 정합니다. exporter·provenance는 `server.log_file`, relay는 최상위 `log_file`이고, `log_max_size`(기본 50MB)를 넘으면 `log_backups`(기본 5)개까지 돌립니다. 지정하지 않으면 지금처럼 stdout으로 씁니다(Docker·systemd).
`./smoke-test.sh`는 묶음을 풀어 세 서비스의 시작·상태·중지를 확인합니다(CI). 설치 절차는 [INSTALL.md 3.5](../INSTALL.md#35-대안-설치-없이-스크립트로-실행)에 있습니다.

## Provenance 조회 서비스 (`nifi-provenance-query`)

같은 패키지의 두 번째 진입점입니다(`src/nifi_exporter/provenance.py`). Grafana 링크에서 Processor 하나와 시각을 받아 NiFi Provenance를 조회합니다.

- 흐름: `POST /provenance`(searchTerms `ProcessorID`, `startDate`·`endDate`, `maxResults`, `summarize: true`) → `GET /provenance/{id}`를 `finished`까지 `poll_interval` 간격으로 폴링 → 결과 반환 → `DELETE /provenance/{id}`. DELETE는 실패·타임아웃 때도 실행합니다.
- 강제와 제한: `processor_id`(UUID)와 시간 범위(`at`[+`window`] 또는 `from`+`to`)가 없으면 400입니다. 범위는 `provenance.max_range`(기본 1시간)로 줄이고, 결과는 `max_results`(기본 1000)까지, 동시 조회는 `max_concurrent`(기본 2, 넘으면 429)까지입니다. `cluster`가 `nifi.cluster_name`과 다르면 400입니다.
- 반환 필드: 이벤트 id·시각·종류, 컴포넌트 id·이름, Process Group id, FlowFile UUID, 크기, 노드 주소, Relationship, Transit URI, 상세. 속성과 내용은 요청하지도 반환하지도 않습니다.
- NiFi 계정: `/provenance` 읽기와 대상 컴포넌트의 Provenance 보기 권한(이름까지 보려면 컴포넌트 읽기 권한)이 필요합니다. exporter 계정과 분리합니다(루트 README 4.6).

```bash
.venv/bin/nifi-provenance-query --config provenance.yaml --check-config
.venv/bin/nifi-provenance-query --config provenance.yaml
curl -s "localhost:9104/provenance?processor_id=<UUID>&at=$(date +%s)000&window=5m&format=json"
```

Docker에서는 같은 이미지를 `--entrypoint nifi-provenance-query`로 실행하고 `--config`를 넘깁니다(진입점을 바꾸면 기본 CMD가 적용되지 않습니다).

## 알림 중계 서비스 (`nifi-alert-relay`)

세 번째 진입점입니다(`src/nifi_exporter/alert_relay.py`). Alertmanager의 webhook 수신처(`custom-relay`)로 `POST /alerts`를 받아, 설정한 대상(target)마다 다시 HTTP로 보냅니다. Slack·메일 외의 사내 시스템 API를 부를 때 씁니다. 설정 파일 형식은 exporter와 다릅니다: `config/nifi-alert-relay.example.yaml`.

- 대상별: `url`, `method`, `headers`(값의 `${ENV}`는 시작할 때 환경변수로), `mode`(`alert`: 알림마다 요청 / `group`: 통지마다 요청), `payload`(생략하면 원본, 지정하면 JSON 구조의 문자열 자리를 채움), `match`(레이블 또는 `status`), `send_resolved`, `timeout`, `retries`(5xx·429·연결 오류만), `retry_backoff`, `tls`.
- 템플릿 필드(alert 모드): `status`, `alertname`, `severity`, `cluster`, `summary`, `description`, `startsAt`, `endsAt`, `generatorURL`, `fingerprint`, `receiver`, `externalURL`, `labels[이름]`, `annotations[이름]`. 값이 정확히 `{labels}`, `{annotations}`, `{alert}`이면 객체를 그대로 넣습니다. group 모드는 `count`, `firing`, `resolved`, `groupKey`, `labels[이름]`(공통 레이블), `{alerts}`, `{groupLabels}`, `{commonLabels}`를 씁니다. 없는 필드는 빈 문자열입니다.
- 대상 하나라도 실패하면 502를 돌려 Alertmanager가 다시 보내게 하고, 이미 성공한 대상은 `dedupe_window`(기본 5분) 동안 다시 보내지 않습니다. 같은 키가 전송 중이면 중복 전송 없이 502를 반환합니다. 전송 실패·예외 시 예약을 해제해 재시도를 허용합니다. 이 보호는 relay 프로세스 안에서 적용됩니다.
- group 모드의 `status`, `commonLabels`, `commonAnnotations`와 관련 템플릿 필드는 필터링 후 남은 알림으로 다시 계산합니다. 모두 해소됐으면 `resolved`이며, 하나라도 발화 중이면 `firing`입니다. 그룹 키와 라우팅 정보는 유지합니다.
- 엔드포인트: `POST /alerts`, `GET /metrics`(`nifi_alert_relay_deliveries_total{target,result}`, `nifi_alert_relay_alerts_total`, `nifi_alert_relay_last_success_timestamp_seconds`, `nifi_alert_relay_notifications_total`), `GET /healthz`. `basic_auth`를 두면 `/healthz`를 뺀 경로를 보호합니다.

```bash
.venv/bin/nifi-alert-relay --config relay.yaml --check-config
```

## 개발

```bash
make lint   # ruff
make test   # pytest
```

테스트는 세 종류입니다.

- 가짜 NiFi(`tests/fixtures/*.json`)에 대한 단위 테스트: collector, 설정 검증(HTTP·인증 없음 포함), 인증, 클라이언트, 단일 노드 인식, 실패 처리와 재시도, 노드별 Bulletin 동작
- 실제 응답 회귀 테스트(`tests/test_samples.py`): `../design/samples/`에 수집한 응답(루트 README 9.4)으로 모든 컴포넌트가 메트릭이 되는지 확인합니다. 샘플이 없으면 건너뜁니다
- 실제 TLS 핸드셰이크 테스트(`tests/test_tls.py`): openssl로 만든 인증서로 mTLS를 확인합니다(openssl이 없으면 건너뜁니다)
- 알림 중계 테스트(`tests/test_alert_relay.py`): 설정 검증(`${ENV}` 포함), 템플릿, 필터·`send_resolved`, group 모드, 재시도·실패 보고·중복 방지, 4xx 비재시도, HTTP 엔드포인트·basic auth
- Provenance 조회 테스트(`tests/test_provenance.py`): 요청 검증, 실제 2.6.0 응답(`tests/fixtures/provenance.json`)으로 폴링·삭제, 타임아웃 뒤 삭제, 권한 오류 안내, HTML 이스케이프, 동시 조회 제한, basic auth

픽스처는 collector가 의존하는 NiFi 2.x(2.6.0) 응답 구조를 따릅니다. 실제 클러스터의 응답이 다르면 픽스처와 파서를 함께 고치고, `design/samples/`도 다시 수집합니다(루트 README 9.4).
