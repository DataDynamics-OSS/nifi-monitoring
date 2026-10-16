# 로컬 NiFi 2.6.0 클러스터와 모니터링 스택

ZooKeeper와 mTLS를 쓰는 Apache NiFi 2.6.0 2노드 클러스터(CFM 4.12.0의 업스트림 계열)에, `deploy/`가
설명하는 방식대로 연결한 nifi-exporter, Prometheus, Alertmanager, Grafana를 더한 구성입니다. API 샘플
수집과 처음부터 끝까지의 검증에 씁니다. 고정된 테스트 비밀번호와 자체 서명 CA를 쓰므로 운영용이 아닙니다.

```bash
./gen-certs.sh             # certs/: CA, 노드 키스토어, 클라이언트 인증서, 로컬 비밀값
docker compose up -d       # NiFi 두 노드가 연결될 때까지 약 1분
python3 seed.py            # 관리자 정책, 테스트 플로우, 읽기 전용 계정, Provenance 조회 계정
python3 capture_samples.py # CN=nifi-monitor로 design/samples/ 수집
python3 compare.py         # NiFi API 값과 Prometheus 값 대조
python3 scenarios.py       # Alertmanager로 확인하는 알림 시나리오 (1시간 넘게 걸립니다)
python3 ../grafana/check_dashboards.py   # 모든 대시보드 쿼리를 Grafana로 실행
python3 ../grafana/check_drilldown.py    # 표 링크 이동과 Provenance 링크 조회를 브라우저로 확인
docker compose down        # 아무것도 보존되지 않습니다
```

TLS·인증이 없는 단일 노드 NiFi와 그 exporter는 `plain` 프로필로 따로 띄웁니다.

```bash
docker compose --profile plain up -d nifi-plain nifi-exporter-plain
python3 capture_samples.py --url http://localhost:18090 --out ../../design/samples/standalone
```

| 서비스 | URL | 로그인 |
|---|---|---|
| NiFi | https://localhost:18443/nifi (nifi-2: 18444) | 브라우저에 `certs/admin.p12` 등록 (비밀번호 `localtest`) |
| nifi-exporter | http://localhost:19103/metrics | `prometheus` / `localtest` |
| Provenance 조회 (`provenance-query`) | http://localhost:19104 (127.0.0.1 전용) | 없음 |
| 알림 중계 (`nifi-alert-relay`) | http://localhost:19107/metrics (127.0.0.1 전용) | `alertmanager` / `localtest` |
| 시험 수신처 (`alert-sink`) | http://localhost:19108/requests (127.0.0.1 전용) | 없음 |
| Prometheus | http://localhost:19090 | |
| Alertmanager | http://localhost:19093 | |
| Grafana | http://localhost:13000 | `admin` / `localtest` (화면 캡처용으로 읽기 전용 익명 접근도 켜져 있습니다) |
| NiFi (plain 프로필) | http://localhost:18090/nifi | 없음 (TLS·인증 없는 단일 노드) |
| nifi-exporter (plain 프로필) | http://localhost:19105/metrics | 없음 |

Prometheus는 운영 규칙(`../prometheus/rules`)을, Alertmanager는 운영 설정(`../alertmanager`)을 그대로
읽습니다. 이 디렉터리의 `prometheus.yml`은 운영 스크레이프 설정을 로컬 대상으로 바꾼 사본입니다.
Slack/SMTP/호출기 발송은 로컬에서 실패하는 것이 정상이며, 알림 상태는 Alertmanager API로 읽습니다.

| 파일 | 용도 |
|---|---|
| `gen-certs.sh` | 테스트 PKI(SAN `nifi-N`, `localhost`인 노드 인증서, 클라이언트 `admin`, `nifi-monitor`, `prometheus`, `nifi-provenance`)와 로컬 비밀값. 이미 있는 파일은 유지하므로 기존 `certs/`에서 다시 실행하면 빠진 인증서만 만듭니다 |
| `nifi-entrypoint.sh` | 두 노드 identity를 `authorizers.xml`에 넣은 뒤 이미지의 `start.sh`를 실행합니다 |
| `seed.py` | 멱등: 관리자 루트 PG 정책, 테스트 플로우, `CN=nifi-monitor`, `CN=prometheus`(내장 메트릭, `/flow` 읽기만), `CN=nifi-provenance`(`/provenance` 읽기, 루트 PG의 Provenance 보기·읽기) |
| `exporter.yaml` | exporter 설정: `CN=nifi-monitor`로 mTLS, `/metrics` basic auth |
| `alert-relay.yaml` | 알림 중계 설정: critical 알림을 템플릿 본문으로(`sink-critical`), 모든 통지를 원본 그대로(`sink-raw`) 시험 수신처에 보냅니다 |
| `alert_sink.py` | 시험 수신처(`alert-sink`): 받은 요청을 기록하고 `GET /requests`로 돌려줍니다. `/fail` 경로는 503을 돌려줍니다 |
| `provenance-query.yaml` | Provenance 조회 서비스 설정: `CN=nifi-provenance`로 mTLS, 최대 1시간·1000건. 서비스는 exporter 이미지를 `nifi-provenance-query` 진입점으로 실행합니다 |
| `capture_samples.py` | API 응답을 `design/samples/`에 저장합니다. 다른 클러스터(CFM)에는 `--url`, `--cert-dir`, `--cert`. `http://` 주소는 인증서 없이 요청하고, 단일 노드의 `/controller/cluster`(404)는 건너뜁니다 |
| `mask_samples.py` | 운영(CFM)에서 받은 샘플의 컴포넌트 이름·주석·관계 이름을 `name-001` 형태로 바꾸고, Processor 설정(속성)과 Bulletin 메시지를 지우고, `--host`로 준 IP·호스트명을 바꿉니다. 지운 원문이 남으면 1로 끝납니다. 내장 메트릭 파일은 복사하지 않습니다 |
| `nifi-plain-entrypoint.sh` | `plain` 프로필: `nifi.properties`를 HTTP·무인증으로 바꾼 뒤 `nifi.sh`를 직접 실행합니다(이미지의 `start.sh`는 HTTPS를 강제합니다) |
| `exporter-plain.yaml` | `plain` 프로필 exporter 설정: `http://nifi-plain:8080`, `auth.mode: none` |
| `compare.py` | NiFi API의 노드·PG·큐·Processor 값과 Prometheus 값, 그리고 내장 엔드포인트 합계와 exporter 집계값을 비교합니다. `http://` NiFi는 인증서 없이 읽고, `--no-builtin`은 내장 엔드포인트 비교를 뺍니다(`../cfm` 참고) |
| `scenarios.py` | 알림 시나리오: `baseline`, `node`, `exporter`, `permission`, `growth`, `disk` |
| `nifi-ui-proxy.conf` | 화면 캡처 전용(`--profile screenshots`): nginx가 관리자 클라이언트 인증서를 제시해 headless Chromium이 http://localhost:18480/nifi 에서 NiFi UI를 열 수 있게 합니다. 127.0.0.1에만 열려 있으며 절대 외부에 노출하지 않습니다 |

`seed.py`가 만드는 테스트 플로우:

- `/ingest`: GenerateFlowFile(초당 1개) → `to-sink`(Backpressure 100개) → `sink`(Stopped). 큐가 차서 Backpressure가 발동합니다.
- `/ingest/errors`: GenerateFlowFile(5초마다) → ERROR 레벨 LogMessage. ERROR Bulletin을 만듭니다.
- `/broken`: 연결이 없는 GenerateFlowFile이라 Invalid입니다.
- `/stall`: GenerateFlowFile(10초마다) → `to-hourly` → `hourly`(Running, 1시간에 한 번 실행). 하류가 Running인데 소비하지 않습니다.
- `/ports`: 입력 포트 `in` → funnel → 출력 포트 `out`. 루트에는 입력 포트 `s2s-in`과 nifi-1을 가리키는 Remote Process Group(전송하지 않음)이 있습니다. 포트와 RPG 메트릭용입니다.
- `/disk`: GenerateFlowFile(초당 2MB, 정지 상태로 생성) → `to-hold` → `hold`(Stopped). `scenarios.py disk`가 이를 시작해 nifi-2의 300MB content 저장소(tmpfs)를 채웁니다.
