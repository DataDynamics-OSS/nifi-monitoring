# Grafana 대시보드

`build_dashboards.py`로 생성해 provisioning하는 대시보드 6종입니다(폴더 **NiFi**, 태그 `nifi`).

| 대시보드 | uid | 내용 |
|---|---|---|
| NiFi / 개요 | `nifi-overview` | 수집기 상태, 연결된 노드·연결 안 된 노드, Invalid 프로세서, 80% 초과 큐, Backpressure 발동 큐, ERROR Bulletin, 노드 표(상태·heartbeat·스레드·적체·heap·가장 높은 저장소·스레드 풀·가동 시간), heap·저장소 게이지, 클러스터 적체 추이, 발화 중인 알림 |
| NiFi / 프로세스 그룹 | `nifi-process-groups` | 선택 그룹과 직속 하위 그룹 표: 경로, 적체, Δ10분, 스레드, 유입·유출 5분, 상태별 프로세서 수. 경로를 클릭하면 하위 그룹이나 그 그룹의 프로세서·큐 화면으로 이동합니다 |
| NiFi / 프로세서 | `nifi-processors` | 선택 그룹의 프로세서 표: 상태, 스레드, 강제 종료, Task, 평균 Task 시간, 유입·유출, 읽기·쓰기, ERROR Bulletin. 프로세서별 추이. 이름 메뉴에서 그 그룹의 큐로 가거나 Provenance를 조회합니다 |
| NiFi / 큐 | `nifi-queues` | 선택 그룹의 큐를 Backpressure 사용률 순으로 보여 줍니다: 보내는 쪽 → 받는 쪽, 사용률, 적체, Δ5분·Δ10분, 임계치, 받는 쪽 실행 중 여부 |
| NiFi / 장애 분석 | `nifi-incident` | 알림 발화 시점 표시, 프로세서별 ERROR Bulletin, 가장 빨리 쌓이는 큐, Backpressure 상위 10, 가장 느린 프로세서, 노드·heap·GC 추이. ERROR Bulletin·가장 느린 프로세서 그래프의 점을 클릭하면 그 시점까지 5분의 Provenance를 조회합니다 |
| NiFi / JVM·스레드 | `nifi-jvm` | 스레드 풀 크기·활성 스레드·강제 종료 스레드·최대 스레드 풀 사용률, 노드별 스레드 풀 사용률, 활성 스레드와 스레드 풀 크기, JVM 스레드 수(전체·daemon), JVM 가동 시간, Heap 사용·확보·최대, Heap 사용률, Non-heap, GC 시간 비율, GC 횟수 |

모든 대시보드는 맨 위에 수집기 상태 줄이 있습니다. 여기가 "실패"이면 아래 값은 0이 아니라 *미수집*입니다.

화면 문구는 한국어입니다. 메트릭 이름, NiFi 상태값(Running, Invalid 등), NiFi 용어(Backpressure, Bulletin, FlowFile, Heap)는 원어를 유지합니다. uid와 파일 이름은 영어 그대로라 링크와 provisioning은 바뀌지 않습니다.

## 파일

```
build_dashboards.py                 대시보드를 코드로 정의합니다 → dashboards/*.json
check_dashboards.py                 실제 Grafana에서 모든 패널 쿼리를 실행합니다
check_drilldown.py                  표 셀 data link를 브라우저에서 클릭해 이동 결과를 확인합니다
push_dashboards.py                  provisioning 파일을 둘 수 없을 때 Grafana HTTP API로 올립니다
dashboards/*.json                   생성물입니다. 커밋하고 읽기 전용으로 provisioning합니다
provisioning/datasources/prometheus.yaml   uid "prometheus", 주소는 $PROMETHEUS_URL
provisioning/dashboards/nifi.yaml          파일 provider → /var/lib/grafana/dashboards/nifi
```

## 대시보드 수정

`build_dashboards.py`를 고친 뒤 다음을 실행합니다.

```bash
python3 build_dashboards.py            # dashboards/*.json 재생성
python3 build_dashboards.py --check    # CI: 생성 결과가 최신인지 확인
python3 check_dashboards.py            # 로컬 스택(deploy/local, Grafana :13000)에서 쿼리 검사
python3 check_drilldown.py             # 로컬 스택에서 표 링크 6개 이동과 Provenance 링크 3개 조회를 브라우저로 확인
```

`check_drilldown.py`는 headless Chromium과 Node 22 이상이 필요합니다(`docs/diagrams/cdp.mjs` 사용). Provenance 링크 3개(프로세서 표, 장애 분석 그래프 2개)는 주소를 읽어 nifi-provenance-query를 직접 호출하므로 로컬 `provenance-query` 서비스도 떠 있어야 합니다.

Provenance 링크는 숨은 상수 변수 `provenance_url`(nifi-provenance-query 주소)을 씁니다. 기본값은 로컬 스택의 `http://localhost:19104`입니다. 운영에서는 사용자 브라우저가 닿는 주소로 다시 생성합니다.

```bash
NIFI_PROVENANCE_URL=https://nifi-provenance.example.com python3 build_dashboards.py
```

이렇게 만든 JSON은 저장소의 JSON과 달라지므로 CI의 `--check`는 기본값으로 실행합니다. 운영 배포물은 배포 단계에서 생성합니다.

provider가 `allowUiUpdates: false`로 설정되어 있어 UI에서 바꾼 내용은 저장되지 않습니다. git의 JSON이 항상 원본입니다.

## 배포

`provisioning/`을 `/etc/grafana/provisioning`에, `dashboards/`를 `/var/lib/grafana/dashboards/nifi`에 마운트하고 `PROMETHEUS_URL`을 설정합니다(`deploy/local/docker-compose.yml` 참고). Grafana 11.6 이상이 필요합니다(11.6.0에서 확인). 11.3.0에서는 "하위 그룹으로" 링크를 누르면 주소와 변수는 바뀌지만 표가 다음 자동 새로고침(30초)까지 이전 그룹을 보여 줍니다.

### API로 올리기

Grafana 서버의 파일시스템에 provisioning 파일을 둘 수 없으면(다른 팀이 관리하는 Grafana, 컨테이너 플랫폼 등) `push_dashboards.py`가 대시보드 생성과 등록을 한 번에 합니다. 저장소의 `dashboards/*.json`은 바꾸지 않습니다.

```bash
python3 push_dashboards.py \
  --grafana https://grafana.example.com --token-file ~/.grafana-token \
  --provenance-url https://nifi-provenance.example.com \
  --prometheus-url http://prometheus.example.com:9090 \
  --timezone Asia/Seoul
```

1. `build_dashboards.py`로 대시보드 6개를 메모리에서 생성하고 `provenance_url`(사용자 브라우저가 여는 주소)과 시간대를 지정값으로 바꿉니다.
2. `--prometheus-url`을 주면 uid `prometheus`인 Prometheus 데이터소스를 만들거나 주소를 고칩니다(Admin 권한). 주지 않으면 그 uid가 있는지만 확인합니다. 이미 다른 uid로 등록된 Prometheus를 쓰려면 `--datasource-uid`로 지정합니다.
3. 폴더 **NiFi**(uid `nifi`)를 만들고 같은 uid의 대시보드를 덮어씁니다(Editor 권한). 다시 실행하면 version이 올라가며 덮어씁니다.
4. 올린 대시보드를 다시 읽어 폴더와 `provenance_url` 값을 확인합니다.

인증은 서비스 계정 토큰(`--token`, `--token-file`, 환경 변수 `GRAFANA_TOKEN`) 또는 `--user admin:비밀번호`입니다. 주소는 `GRAFANA_URL`, `NIFI_PROVENANCE_URL`, `PROMETHEUS_URL` 환경 변수로도 줄 수 있고, `--dry-run`은 생성 결과만 보여 줍니다. 사설 CA는 `--ca-file`로 지정합니다.

provisioning으로 이미 등록된 대시보드는 Grafana가 API 저장을 거부하므로 두 방식을 섞어 쓰지 않습니다. API로 올린 대시보드는 화면에서 고칠 수 있지만 원본은 `build_dashboards.py`이고, 고친 내용은 다음 실행 때 덮어씁니다.
