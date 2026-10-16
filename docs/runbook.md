# NiFi 모니터링 Runbook

알림별 의미와 먼저 볼 곳, 조치를 정리합니다. 규칙은 `deploy/prometheus/rules/nifi-alerts.yml`, 라우팅·억제는 `deploy/alertmanager/alertmanager.yml`, 대시보드는 Grafana의 **NiFi** 폴더에 있습니다.

대상은 Apache NiFi 2.6.0(CFM 4.12.0)입니다. 임계치는 1차 값이며 운영 2주 후 조정합니다(아래 "임계치 조정 기록").

## 공통 원칙

1. **수집 알림을 먼저 봅니다.** `NiFiExporterDown` / `NiFiCollectorFailing`이 떠 있으면 NiFi 상태 알림은 억제되고, 대시보드의 빈 값은 "0"이 아니라 "미수집"입니다. 수집부터 복구합니다.
2. **노드 알림이 그다음입니다.** `NiFiNodeDisconnected` 중에는 큐·Processor·Bulletin 알림이 억제됩니다(노드 단절의 결과일 가능성이 높기 때문입니다).
3. 큐 알림은 원인 컴포넌트를 찾는 출발점입니다: **큐 대시보드 → 받는 쪽 프로세서 → Bulletin → (필요하면) Provenance**. Provenance는 장애 분석 대시보드의 ERROR Bulletin·가장 느린 프로세서 그래프에서 점을 클릭하거나, 프로세서 표의 이름 메뉴에서 조회합니다(그 시점까지 5분, 최대 1000건, 속성·내용 없음). 더 넓은 범위나 FlowFile 내용은 NiFi UI의 *Data Provenance*에서 봅니다.
4. 대시보드 상단의 **수집기 상태** 패널이 "실패"이면 그 화면의 값은 믿지 않습니다.
5. NiFi 상태 알림은 조건이 사라져도 **5분간 firing을 유지합니다**(`keep_firing_for`). 수집이 끊긴 순간 "resolved"가 잘못 나가지 않게 하기 위해서이며, 그 대신 실제 해소 통지도 최대 5분 늦습니다.
6. **Prometheus를 재시작하면** `for` 상태가 복원되는 동안 알림이 Alertmanager에서 잠시 해소됐다가 다시 발화할 수 있습니다(로컬 검증에서 약 5분). 재시작 직후의 resolved·재발화 통지는 무시합니다.

억제 관계(요약):

| 발화 중인 알림 | 억제되는 알림 |
|---|---|
| `NiFiExporterDown`, `NiFiCollectorFailing` | 같은 cluster의 exporter 외 모든 알림 |
| `NiFiNodeDisconnected` | 같은 cluster의 queue / processor / bulletin 알림 |
| `NiFiClusterQuorumLost` | `NiFiNodeDisconnected`, `NiFiNodeHeartbeatStale` |
| `NiFiQueueBackpressureEngaged` | 같은 큐의 `NearBackpressure`, `Growing`, `Stalled` |
| `NiFiHeapCritical` | 같은 노드의 `NiFiHeapHigh`, `NiFiGCTimeHigh` |
| `NiFiRepositoryDiskCritical` | 같은 리포지토리의 `NiFiRepositoryDiskHigh` |
| `NiFiCollectorFailing` | 같은 collector의 `NiFiCollectorStale` |

---

## 수집 (component=exporter, 플랫폼팀)

### NiFiExporterDown — critical
Prometheus가 2분 이상 exporter를 스크레이프하지 못한 상태입니다. NiFi 상태 알림은 모두 억제되어 있습니다.

- 확인: exporter 프로세스·컨테이너 상태, `curl -u prometheus:<pw> http://<exporter>:9103/metrics`, `/healthz`를 봅니다.
- 401이 나오면 Prometheus의 `basic_auth.password_file`과 exporter의 `server.basic_auth`가 일치하지 않는 것입니다.
- 조치: 재시작합니다. 기동 직후 실패하면 `nifi-exporter --check-config -c <config>`로 설정 오류를 확인합니다.
- 알림이 억제되어 있으므로 NiFi 상태는 NiFi UI에서 직접 확인합니다.

### NiFiExporterDuplicate — critical
한 cluster에 exporter가 2개 이상 스크레이프되고 있습니다. `*_info` 조인이 모두 실패해 큐·Processor·Bulletin 알림이 **동작하지 않습니다**.

- 확인: Prometheus Targets에서 `job=nifi-exporter`이면서 `cluster` 레이블이 같은 대상의 수를 봅니다.
- 조치: exporter를 1개만 남깁니다(설계 14장: 단일 인스턴스와 재시작으로 가용성을 확보합니다).

### NiFiCollectorFailing — critical
exporter는 살아 있지만 한 collector가 3분 이상 NiFi API 호출에 실패하고 있습니다. 해당 collector의 메트릭은 노출되지 않습니다.

- 확인: exporter 로그의 `collector failed`(JSON의 `collector`, `error` 필드)와 `nifi_exporter_api_requests_total{endpoint,code}`를 봅니다.
- 원인별 조치:
  - `HTTP 401`(bearer): 서비스 계정 비밀번호가 바뀌었거나 잠겼습니다. `password_file`을 갱신하고 재시작합니다.
  - `HTTP 403`: 정책이 빠졌습니다. `nifi-monitor`에는 `/flow`, `/controller`, `/system` view와 루트 PG view가 필요합니다(설계 4.2). `cluster` collector만 실패하면 `/controller` read를 의심합니다.
  - `bad certificate` / `certificate verify failed`(mtls): 클라이언트 인증서의 만료·교체 여부와 CA 번들을 확인합니다.
  - `HTTP 400 Invalid host header`: exporter가 부르는 호스트명을 `nifi.web.proxy.host`에 추가합니다.
  - `transport error` / 5xx: NiFi 노드가 다운됐거나 과부하입니다. `base_url`을 다른 노드나 LB로 바꿉니다.
  - `topology`만 실패: PG 수가 많아 타임아웃이 났을 수 있습니다. `nifi.timeout`이나 `collectors.topology.interval`을 늘립니다.
  - `cluster`만 실패하고 오류가 `this NiFi node is not connected to its cluster`: exporter가 부르는 노드가 클러스터에서 끊겼습니다. 단일 노드 NiFi는 자동으로 알아보므로(`nifi_cluster_clustered` 0) 이 오류가 나지 않습니다. 끊긴 노드를 복구하거나 `base_url`을 연결된 노드나 LB로 바꿉니다.
- 설정 오류(예: `http://` 주소에 `bearer`/`mtls` 인증)는 이 알림이 아니라 exporter 기동 실패로 드러납니다. TLS 없는 NiFi에는 인증이 없으므로 `auth.mode: none`을 씁니다(`nifi-exporter --check-config`로 확인).
- 실패한 collector는 주기와 상관없이 30초 뒤 다시 시도하므로, 복구되면 1분 안에 자동으로 해소됩니다.

### NiFiCollectorStale — warning
마지막 수집 성공 후 collector 주기의 3배(최소 3분)가 지났습니다. 실패는 아니지만 수집이 밀리고 있습니다.

- 확인: `nifi_exporter_collector_duration_seconds{collector}`가 주기에 가까운지 봅니다.
- 조치: flow collector이면 응답 크기를 확인합니다(10MB 이상이면 주기를 60s로 늘리거나 `exclude_pg_ids`를 씁니다). topology이면 `max_concurrency`를 늘립니다.

---

## 클러스터 / 노드

### NiFiNodeDisconnected — critical
노드가 2분 이상 CONNECTED가 아닙니다. 큐·Processor·Bulletin 알림은 억제됩니다.

- 확인: 개요 대시보드의 노드 표에서 상태(DISCONNECTED / OFFLOADED / CONNECTING)를 보고, NiFi UI의 Cluster 화면도 봅니다.
- OFFLOADED·DISCONNECTED가 운영자 작업 때문이면 작업이 끝난 뒤 Connect합니다. 예기치 않은 단절이면 노드의 `nifi-app.log`(OOM, 디스크, ZooKeeper 세션 만료)와 네트워크를 확인합니다.
- 재기동 후 노드가 CONNECTING에 머물면 flow 불일치(`flow.json.gz`) 여부를 확인합니다.
- 노드가 재시작됐는지는 JVM·스레드 대시보드의 JVM 가동 시간(`nifi_jvm_uptime_seconds`, 개요 노드 표의 "가동 시간")이 0 근처로 떨어졌는지로 봅니다.

### NiFiNodeHeartbeatStale — warning
마지막 heartbeat 후 60초 이상 지났습니다(기본 heartbeat 주기는 5초이며 8회 누락되면 단절됩니다).

- 확인: 해당 노드의 heap·GC(`NiFiGCTimeHigh` 동반 여부), load, 네트워크 지연을 봅니다.
- 시간대 주의: exporter의 `nifi.timezone`이 NiFi 서버 시간대와 다르면 값이 시간대 차이만큼 틀어집니다. `/nifi-api/flow/about`의 `timezone`을 확인합니다.

### NiFiClusterQuorumLost — critical
연결된 노드가 과반 미만입니다. 개별 노드 알림은 억제됩니다.

- 즉시 NiFi 담당자를 호출합니다. ZooKeeper 상태(`echo ruok | nc <zk> 2181`)와 노드들에 공통된 원인(네트워크 분리, 공유 스토리지)을 확인합니다.

---

## 자원 (JVM / 리포지토리)

### NiFiHeapHigh — warning (85%, 10분) / NiFiHeapCritical — critical (95%, 3분)
- 확인: JVM·스레드 대시보드의 Heap 사용량(사용·확보·최대)과 GC 시간 비율을 봅니다(장애 분석 대시보드에도 있습니다). GC 직후에도 사용량이 최대에 가까우면 heap이 부족한 것입니다. 특정 노드만 높으면 그 노드에 처리가 몰린 것입니다(Primary Node 전용 Processor, 부하 분산이 안 된 큐).
- 원인 후보: 큰 FlowFile 속성, 메모리에 올리는 Processor(MergeContent의 대량 bin, SplitText의 대형 파일), 큐 swap 임계치(`nifi.queue.swap.threshold`)입니다.
- 조치: 원인 Processor의 동시성·batch를 조정하고 큐 적체를 해소합니다. 반복되면 `bootstrap.conf`의 `-Xmx`를 늘립니다(노드 재기동이 필요합니다). Critical은 OOM이 임박한 상태이므로 상류 Processor를 일시 정지하는 것도 고려합니다.

### NiFiGCTimeHigh — warning
최근 5분 동안 GC 시간이 20%를 넘었습니다. heap 알림과 함께 뜨면 메모리 압박이고, 단독으로 뜨면 할당이 많은 처리입니다.

### NiFiThreadPoolSaturated — warning
노드의 timer-driven 스레드 풀 사용률(활성 스레드 / `maxTimerDrivenThreadCount`)이 90% 이상인 상태가 10분 지속됐습니다. Processor가 실행할 스레드를 기다리느라 특정 큐가 아니라 여러 큐가 함께 쌓입니다.

- 확인: JVM·스레드 대시보드에서 노드별 스레드 풀 사용률과 활성 스레드를 보고, 프로세서 대시보드에서 평균 Task 시간이 긴 Processor와 활성 스레드가 많은 Processor를 찾습니다.
- 원인 후보: 외부 시스템 호출 지연(DB, HTTP, HDFS)으로 스레드가 오래 묶임, 동시성(`Concurrent Tasks`)을 과도하게 준 Processor, 짧은 실행 주기로 계속 도는 Processor입니다.
- 조치: 오래 걸리는 Processor의 원인(외부 시스템)을 먼저 해소하고 과도한 동시성을 줄입니다. 그래도 부족하면 `maxTimerDrivenThreadCount`를 늘리되, 노드의 CPU 코어 수(대시보드의 가용 CPU, `nifi_system_available_processors`)와 load average를 함께 보고 정합니다.
- 강제 종료 스레드가 함께 늘면 `NiFiProcessorTerminatedThreads` 절을 봅니다.

### NiFiRepositoryDiskHigh — warning (80%) / NiFiRepositoryDiskCritical — critical (92%)
- `repo` 레이블로 저장소를 구분합니다: `content`, `flowfile`, `provenance`.
- content: 큐 적체가 주원인입니다. 큐 대시보드에서 `적체 바이트`가 큰 큐를 찾아 소비 측을 복구합니다. `nifi.content.repository.archive.max.usage.percentage`도 확인합니다.
- provenance: `nifi.provenance.repository.max.storage.size/time`을 줄입니다.
- flowfile: 큐의 FlowFile 수가 매우 많을 때 늘어납니다. 적체를 해소합니다.
- Critical: 디스크가 차면 NiFi 처리가 멈춥니다. 상류 수집 정지 → 적체 해소 → 디스크 확장 순서로 대응합니다.

---

## 큐 (component=queue)

### NiFiQueueNearBackpressure — warning
큐가 Backpressure 임계치(객체 수와 바이트 중 큰 쪽)의 80%를 넘은 상태가 5분 지속됐습니다.

- 확인: 큐 대시보드(해당 PG)에서 `사용률`, `Δ10분`, `받는 쪽 실행 중`을 보고, 받는 쪽 프로세서의 스레드·Task·평균 Task·ERROR Bulletin을 봅니다.
- 조치: 받는 쪽의 처리 능력(동시성 `Concurrent Tasks`, 외부 시스템 지연)을 확인합니다. 일시적인 유입 폭주라면 지켜봅니다.

### NiFiQueueBackpressureEngaged — critical
큐가 임계치에 도달해 **상류 Processor가 스케줄되지 않습니다**. 같은 큐의 80%·증가·정체 알림은 억제됩니다.

- 클러스터 주의: 임계치는 **노드별로** 적용됩니다. 노드 하나만 가득 차도 발동합니다(노드 편중이면 부하 분산 설정을 확인합니다).
- 조치: 받는 쪽 복구가 우선입니다. 큐 비우기(Empty queue)는 데이터 유실을 감수할 수 있을 때만 합니다. 임계치 상향은 원인을 해결한 뒤에 판단합니다.

### NiFiQueueGrowing — warning
10분 동안 1,000개 이상 늘었고 현재 1,000개를 넘었습니다.

- 확인: 큐 표에서 유입 증가(보내는 쪽 `유입 5분`)인지 소비 감소(받는 쪽 `유출 5분`)인지 비교합니다.

### NiFiQueueStalled — warning
받는 쪽 Processor가 **Running인데도** 10분 동안 소비가 0이고 적체가 있습니다.

- 흔한 원인: 받는 쪽이 외부 시스템에 막혀 있음(타임아웃 대기), 스레드 고갈(`Threads`가 동시성 상한), yield·penalize 반복, 실행 주기(Run Schedule)가 매우 긺, Primary Node 전용인데 데이터가 다른 노드에 있음.
- 확인: 받는 쪽의 ERROR Bulletin, Active·Terminated 스레드, NiFi UI의 Processor 상태 이력을 봅니다.
- 의존 관계: 받는 쪽 id는 topology collector(300초 주기)에서 옵니다. 새로 만든 연결은 최대 5분 뒤부터 평가됩니다.

---

## Processor (component=processor)

### NiFiProcessorInvalid — warning
Processor가 5분 이상 Invalid 상태입니다.

- 확인: NiFi UI에서 Processor의 경고 아이콘을 봅니다(필수 속성, 비활성 컨트롤러 서비스, 연결되지 않은 relationship).
- 배포 직후라면 배포 절차의 문제입니다. 의도적으로 미완성인 플로우는 Processor를 Disabled로 바꾸면 알림이 해소됩니다.

### NiFiProcessorTerminatedThreads — warning
강제 종료(Terminate)된 스레드가 남아 있습니다. 스레드가 실제로 끝나지 않으면 리소스를 계속 잡습니다.

- 조치: 해당 Processor를 정지했다가 시작합니다. 그래도 남으면 노드 재기동 일정을 검토합니다.

### NiFiProcessorSlowTasks — warning
최근 5분 평균 Task 시간이 30초를 넘은 상태가 10분 지속됐습니다.

- 확인: 외부 호출(DB, HTTP, HDFS) 지연과 batch 크기를 봅니다. 장애 분석의 **가장 느린 프로세서** 그래프에서 점을 클릭하면 그 시점의 Provenance 이벤트(Transit URI, 크기, 노드)를 볼 수 있습니다. 원래 오래 걸리는 Task라면 임계치 예외 처리(규칙에서 해당 Processor 제외)를 검토합니다.

---

## Bulletin (component=bulletin)

### NiFiBulletinErrors — warning
한 source에서 5분 동안 ERROR Bulletin이 10건을 넘었습니다. source가 Processor이면 이름과 타입이 표시되고, 그 밖의 경우(컨트롤러 서비스, Reporting Task, 컨트롤러 자체 = "source controller")에는 id만 표시됩니다.

- 확인: 프로세서 대시보드의 `ERROR Bulletin 5분`과 NiFi UI의 Bulletin Board(메시지 원문)를 봅니다. `log_bulletin_messages: true`이면 exporter 로그에서도 원문을 검색할 수 있습니다. 오류가 난 FlowFile은 장애 분석의 **프로세서별 ERROR Bulletin** 그래프에서 점을 클릭해 Provenance(FlowFile UUID, 이벤트 종류)로 확인합니다.
- Provenance 조회가 실패하면: 502(권한)는 조회 계정의 `/provenance`·Provenance 보기 권한을, 504는 범위를 줄여 다시 조회합니다. "가장 오래된 이벤트"가 조회 범위보다 늦으면 NiFi가 이미 지운 구간입니다(`nifi.provenance.repository.max.storage.time`).
- 값은 하한입니다: NiFi는 컴포넌트당 최근 5건만 약 5분 보관합니다.
- 조치: 메시지를 기준으로 대상 시스템, 자격 증명, 데이터 형식을 확인합니다. 반복되는 오류는 failure relationship 처리(재시도·격리 큐) 설계의 문제일 수 있습니다.


## 알림 중계 (component=relay)

사용자 정의 HTTP 수신처로 보내는 `nifi-alert-relay`의 상태입니다. 이 알림은 Slack으로도 가므로 중계가 멈춰도 받을 수 있습니다. Slack·메일·호출기로 가는 알림은 영향을 받지 않습니다.

### NiFiAlertRelayDown — warning
Prometheus가 5분 넘게 중계 서비스를 스크레이프하지 못했습니다.

- 확인: 컨테이너·프로세스 상태, `/healthz`, 시작 로그의 `config error`(설정 파일, 헤더에 쓴 `${ENV}` 환경변수 누락).
- 영향: 그동안 사용자 정의 대상으로 알림이 가지 않습니다. Alertmanager는 webhook 실패를 재시도하므로, 짧은 중단이면 복구 뒤 다시 전달됩니다.

### NiFiAlertRelayFailing — warning
최근 15분 동안 재시도까지 실패한 전송이 있습니다. `target` 레이블이 대상 이름입니다.

- 확인: 중계 서비스 로그의 `alert relay delivery failed`(HTTP 상태와 응답 앞부분), 대상 API의 상태와 인증 토큰 만료.
- 4xx는 재시도하지 않습니다. 본문 형식이 대상 API와 맞지 않거나(`payload` 템플릿) 토큰이 틀린 경우입니다.
- 5xx·429·연결 오류는 대상별 `retries`만큼 재시도한 뒤 실패로 셉니다. 그러면 Alertmanager가 통지를 다시 보내고, 이미 성공한 다른 대상은 중복 방지로 건너뜁니다.

---

## 임계치 조정 기록

| 날짜 | 알림 | 변경 | 근거 |
|---|---|---|---|
| (운영 2주 후 작성) | | | |

## NiFi 업그레이드 회귀 절차

1. 새 버전(또는 CFM 서비스팩) 클러스터에서 `deploy/local/capture_samples.py --url ... --cert-dir ... --out design/samples/<version>`을 실행합니다.
2. `diff -r design/samples design/samples/<version>`으로 필드 변경을 확인합니다(값 차이는 무시합니다).
3. 샘플을 교체하고 `cd exporter && make test`를 실행합니다. `tests/test_samples.py`가 모든 컴포넌트의 메트릭 생성을 확인합니다.
4. 내장 메트릭 이름이 바뀌었으면 `prometheus.yml`의 allowlist와 builtin recording rule을 수정합니다.
5. 로컬 스택(`deploy/local`)에서 NiFi 이미지 버전을 올리고 `compare.py`, `scenarios.py`, `deploy/grafana/check_dashboards.py`, `deploy/grafana/check_drilldown.py`(Provenance 조회 포함)를 실행합니다.
