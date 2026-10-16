# CFM 클러스터 모니터링 구성

대상 CFM 4.12.0 SP1 클러스터(NiFi `2.6.0.4.12.0.1-9`, 2노드, TLS·인증 없음)에 맞춘 nifi-exporter, Provenance 조회 서비스, Prometheus 설정입니다.

저장소가 공개이므로 **실제 주소는 커밋하지 않습니다.** 설정 파일의 `cfm-nifi.example.com`은 자리표시이고, 실제 주소는 `.env`의 `NIFI_BASE_URL`이 덮어씁니다(`.env`는 `.gitignore`에 있습니다).

## 실행

```bash
cd deploy/cfm
cp .env.example .env                  # NIFI_BASE_URL=http://<CFM 주소>:<포트>
docker compose up -d                  # nifi-exporter:local 이미지가 없으면 빌드합니다
```

| 서비스 | 주소 |
|---|---|
| nifi-exporter | http://localhost:19113/metrics |
| Provenance 조회 | http://localhost:19114 |
| Prometheus | http://localhost:19091 |

모두 127.0.0.1에만 열립니다. CFM에는 조회만 하며, Provenance 조회만 NiFi에 임시 질의를 만들었다가 지웁니다.

수치 대조(체크리스트 3.7):

```bash
python3 ../local/compare.py --nifi "$(sed -n 's/^NIFI_BASE_URL=//p' .env)" \
  --prom http://localhost:19091 --cluster cfm --no-builtin
```

## 파일

| 파일 | 내용 |
|---|---|
| `nifi-exporter.yaml` | `cluster_name: cfm`, `timezone: America/New_York`, `auth.mode: none` |
| `provenance-query.yaml` | 같은 연결 설정 + 최대 1시간·1000건 |
| `prometheus.yml` | 운영 설정(`../prometheus/prometheus.yml`)의 CFM 실값판. 규칙은 `../prometheus/rules`를 그대로 씁니다 |
| `docker-compose.yml` | 위 세 서비스 |
| `.env.example` | `NIFI_BASE_URL` 자리표시 |

## 운영 설정과 다른 점

- **`nifi.timezone: America/New_York`이 필수입니다.** heartbeat가 `EDT`로 옵니다. 기본값 UTC로 두면 heartbeat 경과가 4시간으로 잡혀 `NiFiNodeHeartbeatStale`이 잘못 발화합니다.
- **내장 메트릭 job(`nifi-builtin`)이 없습니다.** CFM 주소는 요청마다 두 노드를 번갈아 응답하는 로드밸런서이고, 노드 호스트명은 모니터링 호스트에서 이름 해석이 되지 않습니다. 내장 엔드포인트는 노드별 값이라 노드를 하나씩 직접 스크레이프해야 하므로 쓸 수 없습니다. exporter는 클러스터 전체 값을 받으므로 영향이 없고, 노드별 큐 분해 화면만 비게 됩니다. 노드에 직접 닿게 되면 `../prometheus/prometheus.yml`의 `nifi-builtin` job을 `scheme: http`로 추가합니다.
- **인증서 경로가 없습니다.** TLS·인증이 없기 때문입니다. 이 compose는 exporter `/metrics`를 내부 망에서만 스크레이프하므로 basic auth를 쓰지 않습니다. 다른 망에 노출하면 exporter의 `server.basic_auth`와 Prometheus의 `basic_auth`를 함께 켭니다.
- **Alertmanager 주소**(`alertmanager:9093`)는 운영 Alertmanager로 바꿉니다. 이 compose에는 Alertmanager가 없어 알림은 Prometheus에서만 보입니다. 수신 채널 실값은 체크리스트 5.18입니다.

## 확인 결과 (2026-10-15)

- 수집기 6개 모두 성공, 규칙 53개(recording 31, alert 22) 모두 정상 평가.
- `compare.py`: 392항목 일치(노드 4, 큐 적체·사용률 294, Process Group 12, Processor 81, Invalid 수 1), 0 failed.
- heartbeat 경과 1~5초(시간대 설정 정상).
- 바로 대기(pending) 상태가 된 알림: `NiFiRepositoryDiskHigh` 6건(두 노드의 저장소 3종이 같은 디스크, 83%), 한 노드의 `NiFiHeapHigh`. 저장소 대응은 운영 전에 정해야 합니다.
