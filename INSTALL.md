# 설치·설정 가이드 (Docker 없이, 처음 하는 분용)

이 문서는 Docker를 쓸 수 없는 리눅스 서버에 NiFi 모니터링 구성 전체를 **한 단계씩** 설치하는 방법입니다. 명령을 위에서부터 차례로 따라 하면 됩니다. 각 단계 끝의 **확인**이 통과해야 다음 단계로 넘어갑니다.

기능 설명과 설정 키 전체 목록은 [README.md](README.md)에 있습니다. 이 문서는 "어떻게 설치하는가"만 다룹니다.

---

## 목차

- [경로 변수](#경로-변수)
  - [root가 필요한 작업](#root가-필요한-작업)
- [설치 전 체크리스트](#설치-전-체크리스트)
  - [내 NiFi는 어떤 유형인가](#내-nifi는-어떤-유형인가)
  - [NiFi 설정 파일 위치](#nifi-설정-파일-위치)
  - [A. 접속 방식과 TLS](#a-접속-방식과-tls)
  - [B. 인증과 권한](#b-인증과-권한)
  - [C. 그 밖의 NiFi 설정](#c-그-밖의-nifi-설정)
  - [D. 모니터링 서버 쪽 보안](#d-모니터링-서버-쪽-보안)
  - [결과별 exporter 설정](#결과별-exporter-설정)
- [0. 무엇을 설치하나](#0-무엇을-설치하나)
- [1. 준비](#1-준비)
  - [1.1 서버 확인](#11-서버-확인)
  - [1.2 네트워크 확인](#12-네트워크-확인)
  - [1.3 실행 계정 정하기](#13-실행-계정-정하기)
  - [1.4 기준 디렉터리와 경로 변수 파일](#14-기준-디렉터리와-경로-변수-파일)
  - [1.5 저장소 받기](#15-저장소-받기)
  - [1.6 시간대를 Asia/Seoul로 고정](#16-시간대를-asiaseoul로-고정)
  - [1.7 인터넷이 안 되는 서버라면 (폐쇄망)](#17-인터넷이-안-되는-서버라면-폐쇄망)
  - [1.8 root 작업 모아 하기](#18-root-작업-모아-하기)
- [2. NiFi 접속 준비](#2-nifi-접속-준비)
  - [2.1 유형 확인](#21-유형-확인)
  - [2.2 유형별 준비](#22-유형별-준비)
  - [2.3 NiFi 시간대 (Asia/Seoul) 확인](#23-nifi-시간대-asiaseoul-확인)
- [3. nifi-exporter 설치](#3-nifi-exporter-설치)
  - [3.1 Python 확인](#31-python-확인)
  - [3.2 설치](#32-설치)
  - [3.3 설정 파일 만들기](#33-설정-파일-만들기)
  - [3.4 서비스 시작](#34-서비스-시작)
  - [3.5 (대안) 설치 없이 스크립트로 실행](#35-대안-설치-없이-스크립트로-실행)
- [4. Prometheus 설치](#4-prometheus-설치)
  - [4.1 내려받기와 설치](#41-내려받기와-설치)
  - [4.2 설정 파일 복사](#42-설정-파일-복사)
  - [4.3 설정 파일 고치기](#43-설정-파일-고치기)
  - [4.4 서비스 시작](#44-서비스-시작)
- [5. Alertmanager 설치](#5-alertmanager-설치)
  - [5.1 내려받기와 설치](#51-내려받기와-설치)
  - [5.2 알림 받을 곳 정하기](#52-알림-받을-곳-정하기)
  - [5.3 서비스 시작](#53-서비스-시작)
- [6. Grafana 설치](#6-grafana-설치)
  - [6.1 설치 확인](#61-설치-확인)
  - [6.2 데이터소스와 대시보드 넣기](#62-데이터소스와-대시보드-넣기)
  - [6.3 시작](#63-시작)
- [7. (선택) Provenance 조회 서비스](#7-선택-provenance-조회-서비스)
  - [7.1 NiFi 조회용 계정 (exporter 계정과 **별도**)](#71-nifi-조회용-계정-exporter-계정과-별도)
  - [7.2 설정과 실행](#72-설정과-실행)
  - [7.3 대시보드 링크 주소 바꾸기](#73-대시보드-링크-주소-바꾸기)
- [8. (선택) 알림 중계 서비스](#8-선택-알림-중계-서비스)
  - [8.1 설정](#81-설정)
  - [8.2 서비스 시작](#82-서비스-시작)
  - [8.3 Alertmanager·Prometheus 연결](#83-alertmanagerprometheus-연결)
- [9. 최종 점검](#9-최종-점검)
- [10. 문제 해결](#10-문제-해결)
- [11. 업데이트와 제거](#11-업데이트와-제거)
  - [11.1 저장소 업데이트 반영](#111-저장소-업데이트-반영)
  - [11.2 제거](#112-제거)

---

## 경로 변수

모든 프로그램·설정·데이터는 기준 디렉터리 **`/appdata/nifi-monitoring`(`MON_HOME`) 한 곳**에 둡니다. `/etc`·`/usr`·`/var` 아래에는 OS가 위치를 정한 것(systemd 서비스 파일, sudo 설정, Grafana 패키지)만 둡니다.

```text
/appdata/nifi-monitoring/            MON_HOME
├── nifi-mon.env                     경로 변수 파일
├── src/                             내려받은 파일, 이 저장소(src/nifi-monitoring)
├── bin/                             prometheus, promtool, alertmanager, amtool
├── nifi-exporter/                   venv/, conf/(config.yaml, 비밀번호·인증서)
├── nifi-provenance-query/conf/      (선택) Provenance 조회 서비스 설정
├── nifi-alert-relay/conf/           (선택) 알림 중계 설정
├── prometheus/                      conf/(prometheus.yml, rules/, secrets/), data/
├── alertmanager/                    conf/(alertmanager.yml, templates/), data/
└── grafana/                         provisioning/, dashboards/nifi/
```

이 문서의 명령은 경로를 **변수**로 씁니다(예: `$EXPORTER_CONF/config.yaml`). 변수 값은 [1.4](#14-기준-디렉터리와-경로-변수-파일)에서 만드는 변수 파일 `/appdata/nifi-monitoring/nifi-mon.env` 한 곳에 모여 있습니다. 다른 디스크나 경로를 쓰려면 `MON_HOME`만 바꾸면 나머지가 따라옵니다.

| 변수 | 기본값 | 들어가는 것 |
|---|---|---|
| `MON_HOME` | `/appdata/nifi-monitoring` | 아래 모든 것의 기준 디렉터리 |
| `SRC_DIR` | `$MON_HOME/src` | 내려받은 설치 파일(tar.gz, rpm/deb, wheel) |
| `REPO` | `$SRC_DIR/nifi-monitoring` | 이 저장소 |
| `BIN_DIR` | `$MON_HOME/bin` | `prometheus`, `promtool`, `alertmanager`, `amtool` 실행 파일. 변수 파일이 `PATH`에 넣습니다 |
| `EXPORTER_HOME` | `$MON_HOME/nifi-exporter` | exporter Python 가상환경(`venv/`). Provenance 조회·알림 중계도 여기서 실행 |
| `EXPORTER_CONF` | `$EXPORTER_HOME/conf` | exporter 설정(`config.yaml`), NiFi 비밀번호·인증서, `/metrics` 비밀번호 |
| `PROVQ_CONF` | `$MON_HOME/nifi-provenance-query/conf` | (선택) Provenance 조회 서비스 설정·비밀번호 |
| `RELAY_CONF` | `$MON_HOME/nifi-alert-relay/conf` | (선택) 알림 중계 설정·비밀번호·토큰 환경 파일 |
| `PROM_CONF` | `$MON_HOME/prometheus/conf` | `prometheus.yml`, `rules/`, `secrets/` |
| `PROM_DATA` | `$MON_HOME/prometheus/data` | Prometheus 수집 데이터 (**디스크를 가장 많이 씀**, 50GB 이상) |
| `AM_CONF` | `$MON_HOME/alertmanager/conf` | `alertmanager.yml`, `templates/`, Slack 웹훅·SMTP 비밀번호 파일 |
| `AM_DATA` | `$MON_HOME/alertmanager/data` | Alertmanager 상태(침묵 설정 등) |
| `GRAFANA_PROV` | `$MON_HOME/grafana/provisioning` | Grafana 데이터소스·대시보드 등록 파일. [1.8](#18-root-작업-모아-하기)에서 Grafana가 이 위치를 읽게 합니다 |
| `GRAFANA_DASH` | `$MON_HOME/grafana/dashboards/nifi` | NiFi 대시보드 JSON 6개 |
| `RUN_USER` | `monitor` | 설치하고 운영하는 계정 ([1.3](#13-실행-계정-정하기)) |
| `EXPORTER_USER`<br>`PROM_USER`<br>`AM_USER` | `$RUN_USER` | 각 서비스를 실행하는 계정. 서비스별 계정(A)이면 `nifi-exporter`, `prometheus`, `alertmanager` |
| `SYSTEMD_DIR` | `/etc/systemd/system` | systemd 서비스 파일. **바꾸지 않음** (OS 표준 위치, root만 씀) |
| `GRAFANA_ENV` | RHEL `/etc/sysconfig/grafana-server`<br>Ubuntu `/etc/default/grafana-server` | Grafana 패키지의 환경 파일. **바꾸지 않음** (OS가 정함, 자동 선택, root만 씀) |

Grafana 프로그램·내부 DB·로그는 rpm/deb 패키지가 정한 위치(`/usr/share/grafana`, `/var/lib/grafana`, `/var/log/grafana`)를 그대로 씁니다. 이 문서가 다루는 Grafana 파일(등록 파일, 대시보드)은 `MON_HOME` 안에 있습니다.

### root가 필요한 작업

root(또는 sudo) 권한은 아래 작업에만 필요합니다. 나머지 설치·설정은 모두 실행 계정(`monitor`)으로 `MON_HOME` 안에서 합니다.

| 단계 | 작업 | root가 필요한 이유 |
|---|---|---|
| [1.3](#13-실행-계정-정하기) | 실행 계정 만들기 | 계정 생성 |
| [1.4](#14-기준-디렉터리와-경로-변수-파일) | `/appdata/nifi-monitoring`을 만들고 실행 계정에 넘기기 | `/appdata` 쓰기 권한 |
| [1.6](#16-시간대를-asiaseoul로-고정) | 서버 시간대 | OS 설정 |
| [1.8](#18-root-작업-모아-하기) | Python 설치, 서비스 파일 등록, Grafana 패키지와 환경 파일, 서비스 제어 위임(sudo), 방화벽 | OS가 정한 위치(`/etc`, `/usr`) |
| [11.2](#112-제거) | 제거 | 위 작업의 반대 |

- 명령 블록 첫 줄이 `# [root]`이면 root로 실행합니다. 표시가 없는 블록은 **실행 계정**으로 실행합니다.
- 서비스 시작·재시작은 `sudo systemctl start nifi-exporter`처럼 적었습니다. 1.8에서 위임해 두면 실행 계정이 비밀번호 없이 이 명령만 쓸 수 있습니다. 위임이 허용되지 않는 서버라면 이 명령만 root에게 요청합니다.

알아 둘 점:

- **터미널을 새로 열 때마다** 변수 파일을 불러와야 합니다. 1.4에서 실행 계정의 `~/.bashrc`에 넣어 두므로 `sudo -iu monitor`로 전환하면 자동으로 불러옵니다. root 셸에서는 `source /appdata/nifi-monitoring/nifi-mon.env`를 직접 실행합니다. 변수가 비어 있으면 명령이 엉뚱한 곳(예: `/config.yaml`)을 가리킵니다. 확인: `echo $EXPORTER_CONF`
- **YAML 설정 파일 안에서는 변수를 쓸 수 없습니다.** 저장소의 설정 파일은 Docker 기준 경로(`/etc/nifi-exporter/password` 등)로 적혀 있으므로, 이 문서는 파일을 복사할 때 `sed`로 내 경로로 바꿉니다(3.3, 4.2, 5.1, 6.2, 8.1). 설정 파일에 경로를 직접 쓸 때는 `echo $EXPORTER_CONF`처럼 실제 경로를 확인해 적습니다. 이 문서의 YAML 예시는 기본값(`/appdata/nifi-monitoring/...`)으로 적었습니다.
- `/appdata`의 디스크 여유는 Prometheus 데이터(`PROM_DATA`) 때문에 50GB 이상이어야 합니다(1.1에서 확인).

---

## 설치 전 체크리스트

설치를 시작하기 전에 **NiFi가 어떤 보안 설정으로 운영되는지** 확인합니다. 결과에 따라 exporter 설정(`nifi.base_url`, `nifi.tls`, `nifi.auth`)과 필요한 파일이 달라집니다. 이 표를 출력하거나 복사해 `☐`를 `☑`로 바꾸며 채웁니다.

NiFi는 **인증(로그인)과 권한(정책) 설정이 아예 없는 경우**도 있습니다. 그래서 먼저 아래 "내 NiFi는 어떤 유형인가"로 유형을 정하고, 유형에 해당하는 항목만 채웁니다.

### 내 NiFi는 어떤 유형인가

| 유형 | 접속 | 인증(로그인) | 권한(정책) | 흔한 경우 | exporter `nifi.auth.mode` |
|---|---|---|---|---|---|
| **① 인증·권한 없음** | `http://` | 없음 (누구나 `anonymous`) | 없음 | 개발·내부망 NiFi, CFM을 보안 없이 설치한 경우 | `none` |
| **② 인증만 있음** (Single User) | `https://` | 관리자 계정 하나 | 없음 (그 계정이 모든 권한) | NiFi 2.x를 기본값으로 설치한 경우 | `bearer` (관리자 계정) |
| **③ 인증·권한 모두** (아이디/비밀번호) | `https://` | LDAP·Kerberos | 사용자별 정책 | 운영 환경 | `bearer` (전용 계정) |
| **④ 인증·권한 모두** (인증서) | `https://` | 클라이언트 인증서 | 사용자별 정책 | 운영 환경 | `mtls` (전용 인증서) |

**판별 순서**

1. 브라우저로 NiFi를 열었을 때 주소가 `http://`이고 로그인 화면 없이 바로 캔버스가 나오면 **①**입니다.
   NiFi 2.x는 HTTPS에서 익명 접속을 허용하지 않으므로, 로그인 없이 열리는 NiFi는 보통 HTTP 구성입니다.
2. `https://`이면 `nifi.properties`의 두 값을 봅니다.
   - `nifi.security.user.authorizer=single-user-authorizer` → **②**
   - `nifi.security.user.login.identity.provider`가 `ldap-provider`·`kerberos-provider` → **③**
   - 로그인 방식이 비어 있고 브라우저 인증서로 들어가면 → **④**
3. 확실하지 않으면 모니터링 서버에서 "지금 나는 누구로 보이는가"를 물어봅니다.

   ```bash
   curl -s http://nifi.example.com:8080/nifi-api/flow/current-user | grep -o '"identity":"[^"]*"'
   ```

   `"identity":"anonymous"`가 나오면 **①**(인증·권한 없음)이 확실합니다. `401`이나 접속 오류가 나면 HTTPS 쪽(②~④)입니다.

**유형별로 채울 항목**

| 유형 | A. 접속·TLS | B. 인증·권한 | C. 그 밖 | D. 모니터링 서버 보안 |
|---|---|---|---|---|
| ① | A1~A3, A8 (A4~A7 인증서 항목은 건너뜀) | **B0만** (B1~B8 건너뜀) | C2, C3 (C1·C4 건너뜀) | 전부, 특히 **D6·D7** |
| ② | 전부 | B0~B2, B8, **B9** (B3·B4·B5~B7 건너뜀) | 전부 (C4는 건너뜀) | 전부, 특히 **D8** |
| ③ | 전부 | B0~B4, B8 | 전부 | 전부 |
| ④ | 전부 | B0~B2, B4~B7 | 전부 | 전부 |

### NiFi 설정 파일 위치

대부분의 항목은 NiFi 서버의 `nifi.properties`에서 확인합니다. NiFi 관리자에게 열람을 요청하거나 아래 위치에서 봅니다.

| 설치 형태 | `nifi.properties` 위치 |
|---|---|
| Apache NiFi 직접 설치 | `<NiFi 설치 디렉터리>/conf/nifi.properties` |
| Cloudera CFM (Cloudera Manager) | Cloudera Manager → NiFi 서비스 → **구성(Configuration)** 화면. 실제 파일은 NiFi 노드의 `/var/run/cloudera-scm-agent/process/<번호>-nifi-NIFI_NODE/nifi.properties` |

```bash
# NiFi 서버에서: 보안 관련 값만 모아 봅니다
grep -E '^nifi\.(web\.(http|https)\.(host|port)|web\.proxy\.host|security\.(keystore|truststore|user\.login\.identity\.provider|user\.authorizer)|cluster\.is\.node)' \
  <경로>/nifi.properties
```

### A. 접속 방식과 TLS

| # | 확인 항목 | 확인 방법 | 결과 기록 | 영향 |
|---|---|---|---|---|
| A1 | NiFi가 **HTTPS(TLS)**를 쓰는가 | `nifi.web.https.port`에 값이 있으면 HTTPS, `nifi.web.http.port`에만 값이 있으면 HTTP. 브라우저 주소가 `https://`인지로도 알 수 있음 | ☐ HTTPS ☐ HTTP | `nifi.base_url`의 `https://` / `http://` |
| A2 | 접속 포트 | A1의 포트 값 (보통 HTTPS 8443, HTTP 8080) | 포트: ______ | `nifi.base_url` |
| A3 | 모니터링 서버에서 NiFi에 접속되는가 | [1.2](#12-네트워크-확인)의 `curl` 명령. `200`·`401`·`403`이면 연결됨, `000`이면 방화벽 | ☐ 연결됨 ☐ 차단 | 차단이면 방화벽 허용 요청 |
| A4 | 서버 인증서를 누가 발급했나 (HTTPS만) | 아래 `openssl` 명령의 `issuer` | ☐ 공인 CA ☐ 사내(사설) CA ☐ 자체 서명 | 사설·자체 서명이면 **CA 파일 필요** (`nifi.tls.ca_file`) |
| A5 | 인증서에 접속 주소가 들어 있나 (HTTPS만) | 아래 명령의 `subjectAltName`에 exporter가 쓸 호스트명이 있는지 | ☐ 있음 ☐ 없음 | 없으면 인증서에 있는 이름으로 접속하거나 NiFi 관리자에게 재발급 요청 |
| A6 | 인증서 만료일 (HTTPS만) | 아래 명령의 `notAfter` | 만료일: ______ | 만료되면 수집이 멈춤. 갱신 일정 공유 |
| A7 | CA 파일을 **PEM 형식**으로 받았나 (HTTPS만) | `head -1 ca.pem` 결과가 `-----BEGIN CERTIFICATE-----` | ☐ PEM ☐ JKS/PKCS12 (변환 필요) | 아래 변환 명령 |
| A8 | 앞에 **로드밸런서**가 있나 | NiFi 관리자에게 확인. 같은 주소로 여러 번 접속할 때 응답 노드가 바뀌면 로드밸런서 | ☐ 노드 직접 ☐ 로드밸런서 | 로드밸런서면 Prometheus `nifi-builtin` job 사용 불가 ([4.3](#43-설정-파일-고치기)) |

```bash
# A4·A5·A6: 모니터링 서버에서 NiFi 서버 인증서 확인
echo | openssl s_client -connect nifi.example.com:8443 -servername nifi.example.com 2>/dev/null \
  | openssl x509 -noout -issuer -subject -enddate -ext subjectAltName
```

- `issuer`와 `subject`가 같으면 **자체 서명** 인증서입니다.
- `verify return code: 0 (ok)`가 아닌 경우 CA 파일 없이는 접속할 수 없습니다. 확인: `echo | openssl s_client -connect nifi.example.com:8443 2>/dev/null | grep 'Verify return code'`

```bash
# A7: CA를 PEM으로 변환 (NiFi truststore에서 꺼내기)
keytool -list -keystore truststore.jks                                  # 별칭(alias) 확인
keytool -exportcert -rfc -keystore truststore.jks -alias <별칭> -file ca.pem
openssl pkcs12 -in truststore.p12 -nokeys -out ca.pem                   # PKCS12 형식일 때
```

### B. 인증과 권한

| # | 확인 항목 | 확인 방법 | 결과 기록 | 영향 |
|---|---|---|---|---|
| B0 | NiFi 유형 | 위 "내 NiFi는 어떤 유형인가"의 판별 순서 | ☐ ① 인증·권한 없음 ☐ ② Single User ☐ ③ LDAP·Kerberos ☐ ④ 인증서 | 아래 항목 중 무엇을 채울지, 2단계에서 할 일 |
| B1 | 로그인 방식 | `nifi.security.user.login.identity.provider` 값 | ☐ `single-user-provider` ☐ `ldap-provider` ☐ `kerberos-provider` ☐ 비어 있음 | 아래 "결과별 설정" 표 |
| B2 | 권한 관리 방식 | `nifi.security.user.authorizer` 값 | ☐ `single-user-authorizer` ☐ `managed-authorizer` (또는 사내 설정) | Single User면 **읽기 전용 계정을 만들 수 없음** (아래 주의) |
| B3 | (③) 모니터링 전용 계정을 받았나 | [2.2](#22-유형별-준비) | 계정: ______ ☐ 받음 | `nifi.auth.username` |
| B4 | (③·④) 계정에 정책 4개(view)만 있나 | NiFi UI → Policies에서 계정 확인. **modify 권한이 없어야 함** | ☐ `/flow` ☐ `/controller` ☐ `/system` ☐ 루트 PG view | 빠지면 해당 collector 실패 (403) |
| B5 | (인증서 로그인) 클라이언트 인증서·키를 받았나 | 파일 2개: 인증서 PEM, 개인키 PEM | ☐ 인증서 ☐ 개인키 | `nifi.auth.cert_file` / `key_file` |
| B6 | (인증서 로그인) 개인키에 **암호가 없나** | `head -1 client-key.pem`이 `-----BEGIN PRIVATE KEY-----` 또는 `-----BEGIN RSA PRIVATE KEY-----`. `ENCRYPTED`가 보이면 암호 있음 | ☐ 암호 없음 ☐ 암호 있음 (해제 필요) | exporter는 암호 걸린 키를 읽지 못함 |
| B7 | (인증서 로그인) 인증서 DN이 NiFi 사용자로 등록됐나 | `openssl x509 -in client.pem -noout -subject`의 값이 NiFi Users에 있는지 | DN: ______ ☐ 등록됨 | 미등록이면 403 |
| B8 | 토큰 발급 시험 (아이디/비밀번호 로그인) | [2.2](#22-유형별-준비) 끝의 `curl ... /access/token` | ☐ `eyJ...` 받음 | 실패면 계정·비밀번호 확인 |
| B9 | (② Single User) 관리자 아이디·비밀번호를 받았나, 비밀번호를 바꿀 때 알려 주기로 했나 | NiFi 관리자에게 확인. 비밀번호는 NiFi에 해시로만 저장돼 파일에서 꺼낼 수 없음 | ☐ 받음 ☐ 변경 시 통보 합의 | 비밀번호가 바뀌면 exporter가 `401`로 멈춤 |

```bash
# B5·B6: PKCS12(.p12) 하나로 받았을 때 인증서·키 PEM으로 나누기 (키 암호 제거)
openssl pkcs12 -in nifi-monitor.p12 -clcerts -nokeys -out client.pem
openssl pkcs12 -in nifi-monitor.p12 -nocerts -nodes  -out client-key.pem
# 이미 암호 걸린 PEM 키에서 암호 제거
openssl pkey -in client-key-encrypted.pem -out client-key.pem
chmod 600 client-key.pem
```

> **② Single User 주의 (B2가 `single-user-authorizer`)**: 로그인은 있지만 권한(정책) 기능이 없습니다. 사용자가 관리자 하나뿐이라 읽기 전용 계정을 따로 만들 수 없고, exporter도 **플로우를 바꿀 수 있는 관리자 계정**으로 접속하게 됩니다. exporter는 조회(GET)만 하지만, 비밀번호 파일이 새면 NiFi 전체 권한이 새는 것과 같습니다. 비밀번호 파일 권한(D1)을 꼭 지키고, 가능하면 NiFi를 LDAP 등 `managed-authorizer` 구성(③)으로 바꾸도록 NiFi 관리자와 협의합니다.
>
> **① 인증·권한 없음 주의**: 계정도 정책도 없으므로 exporter에 **비밀번호나 인증서가 필요 없습니다.** 대신 NiFi에 접속할 수 있는 사람은 누구나 플로우를 보고 **바꾸고 지울 수 있습니다.** 모니터링 설치와 별개로, NiFi 포트에 접속할 수 있는 범위가 좁은지 NiFi 관리자와 확인합니다(D6).

### C. 그 밖의 NiFi 설정

| # | 확인 항목 | 확인 방법 | 결과 기록 | 영향 |
|---|---|---|---|---|
| C1 | exporter가 쓸 주소가 `nifi.web.proxy.host`에 있나 (HTTPS) | `nifi.web.proxy.host` 값. 노드 호스트명(`nifi.web.https.host`)과 같은 주소로 접속하면 필요 없음 | ☐ 필요 없음 ☐ 추가 요청함 | 빠지면 `400 Invalid host header` |
| C2 | NiFi 시간대가 **Asia/Seoul(KST)**인가 | [2.3](#23-nifi-시간대-asiaseoul-확인) | ☐ KST ☐ 다름 (NiFi 관리자에게 변경 요청) | `nifi.timezone: Asia/Seoul` 고정 (NiFi가 KST가 아니면 heartbeat 알림 오발화) |
| C3 | 클러스터인가 단일 노드인가 | `nifi.cluster.is.node=true`면 클러스터 | ☐ 클러스터 (노드 __개) ☐ 단일 노드 | 설정 변경 없음 (자동 인식) |
| C4 | (선택, Provenance 조회) 조회용 계정을 따로 받았나 | [7.1](#71-nifi-조회용-계정-exporter-계정과-별도) | ☐ 받음 ☐ 사용 안 함 | 7단계 |
| C5 | 모니터링 서버·NiFi 서버 시각이 NTP로 맞춰져 있나 | 각 서버에서 `timedatectl`의 `System clock synchronized: yes` | ☐ 모니터링 서버 ☐ NiFi 서버 | 시각이 어긋나면 heartbeat·알림 시각이 틀림 |

### D. 모니터링 서버 쪽 보안

설치하면서 함께 확인합니다.

| # | 확인 항목 | 해당 단계 | 결과 기록 |
|---|---|---|---|
| D1 | 비밀번호·키 파일 권한이 `600`(디렉터리 `700`)이고 소유자가 실행 계정인가 | 3.3, 4.3, 5.2 | ☐ |
| D2 | exporter `/metrics`에 비밀번호(basic auth)를 걸었나, 또는 내부망으로만 열었나 | 3.3, 4.3 | ☐ 비밀번호 ☐ 내부망 제한 |
| D3 | `insecure_skip_verify: true`를 쓰지 않는가 (임시로 썼다면 CA 파일로 교체) | 3.3 | ☐ |
| D4 | Grafana `admin` 기본 비밀번호를 바꿨나 | 6.3 | ☐ |
| D5 | 외부(사용자 PC)에 연 포트가 Grafana(3000)와 필요한 것(Provenance 9104)뿐인가 | 1.8 | ☐ |
| D6 | (①) NiFi 포트가 신뢰할 수 있는 내부망에만 열려 있는가 | 1.2 | ☐ 해당 없음 ☐ 확인함 |
| D7 | (①) Provenance 조회 서비스를 쓴다면 비밀번호(basic auth)를 걸었나. NiFi에 인증이 없으므로 이 서비스가 유일한 보호 장치임 | 7.2 | ☐ 해당 없음 ☐ 걸었음 |
| D8 | (②) 관리자 비밀번호 파일이 `600`이고 실행 계정만 읽을 수 있는가 | 3.3 | ☐ 해당 없음 ☐ 확인함 |

### 결과별 exporter 설정

체크리스트 결과를 아래 표에서 찾아 [3.3](#33-설정-파일-만들기)에서 그대로 씁니다.

| 유형 | `nifi.base_url` | `nifi.tls` | `nifi.auth` | 준비할 파일 | NiFi에서 할 일 |
|---|---|---|---|---|---|
| ① 인증·권한 없음 | `http://호스트:8080` | 필요 없음 (써도 무시됨) | `{ mode: none }` | 없음 | 없음 |
| ② Single User | `https://호스트:8443` | `ca_file` (A4가 공인 CA면 생략 가능) | `mode: bearer`, `username`(관리자), `password_file` | `ca.pem`, `password` | 없음 (계정·정책 기능이 없음) |
| ③ LDAP·Kerberos | `https://호스트:8443` | `ca_file` (위와 같음) | `mode: bearer`, `username`(전용 계정), `password_file` | `ca.pem`, `password` | 사용자 추가 + 정책 4개 |
| ④ 인증서 | `https://호스트:8443` | `ca_file` | `mode: mtls`, `cert_file`, `key_file` | `ca.pem`, `client.pem`, `client-key.pem` | 인증서 DN 사용자 추가 + 정책 4개 |

> ③ 환경에서도 인증서를 받을 수 있다면 `mtls`를 쓸 수 있습니다. 둘 다 가능하면 **`mtls`를 권장**합니다(비밀번호가 없고 토큰 만료가 없습니다).
>
> `http://` 주소에는 `none`만 쓸 수 있습니다. 다른 값을 넣으면 exporter가 설정 오류로 시작하지 않습니다(NiFi는 HTTP에서 토큰을 발급하지 않습니다).

---

## 0. 무엇을 설치하나

모든 프로그램을 **모니터링 서버 한 대**에 설치합니다. NiFi 서버에는 아무것도 설치하지 않습니다.

![Apache NiFi 통합 모니터링 기술 상세 구성도 — 메트릭 수집·저장·분석, 대시보드·알림 및 선택 서비스](docs/images/architecture-proposal.png)

| 프로그램 | 하는 일 | 포트 | 필수 |
|---|---|---|---|
| nifi-exporter | NiFi 상태를 읽어 숫자(메트릭)로 바꿉니다 | 9103 | 필수 |
| Prometheus | 메트릭을 주기적으로 모아 저장하고 알림 조건을 검사합니다 | 9090 | 필수 |
| Alertmanager | 알림을 Slack·메일 등으로 보냅니다 | 9093 | 필수 |
| Grafana | 대시보드 화면을 보여 줍니다 | 3000 | 필수 |
| nifi-provenance-query | 대시보드에서 클릭하면 NiFi Provenance를 조회합니다 | 9104 | 선택 |
| nifi-alert-relay | 알림을 사내 HTTP API로 다시 보냅니다 | 9105 | 선택 |

검증된 버전입니다. 같은 버전을 쓰기를 권합니다.

| 항목 | 버전 |
|---|---|
| NiFi | 2.6.0 (Cloudera CFM 4.12) |
| Python | 3.11 이상 |
| Prometheus | 2.53.4 (2.42 이상 필요) |
| Alertmanager | 0.28.1 |
| Grafana | 11.6.0 (11.6 이상 필요) |

> 명령은 대부분 실행 계정(`monitor`)으로 실행합니다. root가 필요한 블록은 첫 줄에 `# [root]`라고 적었습니다([root가 필요한 작업](#root가-필요한-작업)).
> 예시의 `nifi.example.com`, `prod-nifi` 같은 값은 **자리표시**입니다. 반드시 실제 값으로 바꿉니다.

---

## 1. 준비

### 1.1 서버 확인

| 항목 | 권장 |
|---|---|
| OS | RHEL/Rocky 8·9, Ubuntu 22.04·24.04 (systemd 사용) |
| CPU / 메모리 | 2코어 / 4GB 이상 |
| 디스크 | `/appdata`에 Prometheus 저장용 50GB 이상 (규모 산정은 [README 9.5](README.md#95-규모-산정)) |
| 아키텍처 | 이 문서는 `amd64`(x86_64) 기준. ARM이면 내려받는 파일 이름의 `amd64`를 `arm64`로 바꿉니다 |

```bash
cat /etc/os-release | head -2      # OS 확인
uname -m                           # x86_64 이면 amd64
df -h /appdata                     # 디스크 여유 확인
```

### 1.2 네트워크 확인

모니터링 서버에서 NiFi에 접속되는지 확인합니다. NiFi 주소와 포트는 NiFi 관리자에게 받습니다.

```bash
# HTTPS NiFi (보통 8443 포트)
curl -k -s -o /dev/null -w "%{http_code}\n" https://nifi.example.com:8443/nifi-api/flow/about
# HTTP NiFi (TLS·인증 없음, 보통 8080 포트)
curl -s -o /dev/null -w "%{http_code}\n" http://nifi.example.com:8080/nifi-api/flow/about
```

- `200`, `401`, `403` 중 하나가 나오면 **연결은 됩니다**(401·403은 로그인이 필요하다는 뜻이라 정상입니다).
- `000`이 나오면 방화벽이나 주소 문제입니다. 네트워크 담당자에게 "모니터링 서버 → NiFi 포트" 허용을 요청합니다.

### 1.3 실행 계정 정하기

프로그램은 root가 아닌 일반 리눅스 계정으로 실행합니다. 계정을 두는 방법은 두 가지이며, **회사 서버 운영 규칙에 맞는 쪽을 하나 고릅니다.**

| 방식 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **B. 하나의 계정** (이 문서의 기본) | `monitor` 같은 계정 하나로 설치하고 모든 프로그램을 실행합니다. 회사가 정한 기존 운영 계정을 써도 됩니다 | root 작업이 1장에 모이고 나머지는 이 계정으로 합니다. 파일 소유자가 하나라 헷갈리지 않습니다 | 모든 프로그램이 서로의 비밀번호 파일(NiFi 비밀번호, Slack 웹훅 등)을 읽을 수 있습니다 |
| **A. 서비스별 계정** (보안 강화) | `nifi-exporter`, `prometheus`, `alertmanager` 계정을 따로 만듭니다 | 한 프로그램이 뚫려도 다른 프로그램의 비밀번호 파일은 읽지 못합니다 | 파일 소유자를 계정마다 나눠야 하므로 설치 전체를 root로 진행합니다 |

**B. 하나의 계정** (기본): 계정 하나를 만듭니다. 회사에서 정한 운영 계정이 있으면 `useradd`는 건너뛰고, 이 문서의 `monitor`를 그 계정 이름으로 바꿔 읽습니다.

```bash
# [root]
useradd -m -s /bin/bash monitor
usermod -aG systemd-journal monitor      # sudo 없이 journalctl로 서비스 로그를 보게 합니다
id monitor                               # uid=...(monitor) ... systemd-journal 이 보이면 됩니다
```

비밀번호를 정하지 않으면 이 계정으로 직접 로그인할 수 없고, 관리자가 `sudo -iu monitor`로만 전환합니다.

**A. 서비스별 계정**: 로그인할 수 없는 시스템 계정 3개를 만듭니다.

```bash
# [root]
useradd --system --no-create-home --shell /sbin/nologin nifi-exporter
useradd --system --no-create-home --shell /sbin/nologin prometheus
useradd --system --no-create-home --shell /sbin/nologin alertmanager
```

A를 골랐다면 이 문서를 이렇게 바꿔 읽습니다.

- 모든 명령을 **root로** 실행합니다. 1.4의 소유자 넘기기와 1.8의 서비스 제어 위임은 건너뜁니다.
- 1.4의 변수 파일에서 `EXPORTER_USER`, `PROM_USER`, `AM_USER`를 각각 `nifi-exporter`, `prometheus`, `alertmanager`로 바꿉니다. 서비스 파일(1.8)의 `User=`와 각 단계의 `chown -R $PROM_USER: ...` 같은 소유자 지정이 이 값을 따릅니다. B에서는 이 `chown`이 아무것도 바꾸지 않습니다.
- 설정 검사(`--check-config`)는 앞에 `sudo -u $EXPORTER_USER`를 붙여, 서비스 계정이 설정·비밀번호 파일을 읽을 수 있는지까지 확인합니다.

**Grafana는 두 방식 모두 패키지가 만드는 `grafana` 계정을 그대로 쓰기를 권합니다.** rpm/deb 패키지가 계정·디렉터리·서비스를 함께 관리하므로 바꾸면 패키지 업데이트 때 권한이 다시 어긋날 수 있습니다. Grafana는 `MON_HOME`의 대시보드 파일을 읽기만 합니다. 회사 규칙상 반드시 하나의 계정이어야 한다면 [6.3](#63-시작)의 "Grafana도 하나의 계정으로 실행하려면"을 따릅니다.

### 1.4 기준 디렉터리와 경로 변수 파일

root가 기준 디렉터리를 만들어 실행 계정에 넘깁니다. 다른 위치를 쓰려면 아래 명령과 변수 파일의 `/appdata/nifi-monitoring`을 모두 같은 값으로 바꿉니다.

```bash
# [root]
mkdir -p /appdata/nifi-monitoring
chown monitor: /appdata/nifi-monitoring      # A(서비스별 계정)면 이 줄은 건너뜁니다
chmod 755 /appdata/nifi-monitoring           # grafana 계정이 대시보드 파일까지 들어올 수 있게 합니다
ls -ld /appdata /appdata/nifi-monitoring     # /appdata 권한의 마지막 글자가 x 여야 합니다 (예: drwxr-xr-x)
```

이제 `sudo -iu monitor`로 실행 계정에 전환하고(A는 root 그대로), 변수 파일을 만듭니다. 경로나 계정 이름을 바꾸려면 `=` 오른쪽만 고칩니다.

```bash
cat > /appdata/nifi-monitoring/nifi-mon.env <<'EOF'
# NiFi 모니터링 경로 변수 (INSTALL.md "경로 변수")
export MON_HOME=/appdata/nifi-monitoring

# 실행 계정 (1.3). A(서비스별 계정)면 아래 세 줄을 nifi-exporter, prometheus, alertmanager로 바꿉니다
export RUN_USER=monitor
export EXPORTER_USER=$RUN_USER
export PROM_USER=$RUN_USER
export AM_USER=$RUN_USER

export SRC_DIR=$MON_HOME/src
export REPO=$SRC_DIR/nifi-monitoring
export BIN_DIR=$MON_HOME/bin
export EXPORTER_HOME=$MON_HOME/nifi-exporter
export EXPORTER_CONF=$EXPORTER_HOME/conf
export PROVQ_CONF=$MON_HOME/nifi-provenance-query/conf
export RELAY_CONF=$MON_HOME/nifi-alert-relay/conf
export PROM_CONF=$MON_HOME/prometheus/conf
export PROM_DATA=$MON_HOME/prometheus/data
export AM_CONF=$MON_HOME/alertmanager/conf
export AM_DATA=$MON_HOME/alertmanager/data
export GRAFANA_PROV=$MON_HOME/grafana/provisioning
export GRAFANA_DASH=$MON_HOME/grafana/dashboards/nifi

# OS가 정한 위치입니다. 바꾸지 않습니다(root만 씁니다)
export SYSTEMD_DIR=/etc/systemd/system
if [ -d /etc/sysconfig ]; then
  export GRAFANA_ENV=/etc/sysconfig/grafana-server     # RHEL / Rocky
else
  export GRAFANA_ENV=/etc/default/grafana-server       # Ubuntu
fi

# prometheus, promtool, alertmanager, amtool을 경로 없이 부를 수 있게 합니다
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) export PATH=$BIN_DIR:$PATH ;; esac
EOF

source /appdata/nifi-monitoring/nifi-mon.env
echo 'source /appdata/nifi-monitoring/nifi-mon.env' >> ~/.bashrc    # 다음 로그인부터 자동으로 불러옵니다
env | grep -E '^(MON_HOME|RUN_USER|SRC_DIR|REPO|BIN_DIR|SYSTEMD_DIR|EXPORTER_|PROVQ_|RELAY_|PROM_|AM_|GRAFANA_)' | sort
```

마지막 명령으로 변수 20개가 모두 값과 함께 나오면 성공입니다.

> root 셸에서 작업할 때(1.6, 1.8)는 먼저 `source /appdata/nifi-monitoring/nifi-mon.env`를 실행합니다. root의 `~/.bashrc`에는 넣지 않아도 됩니다.

### 1.5 저장소 받기

이 저장소를 서버에 둡니다. 인터넷이 되면 git으로 받고, 안 되면 다른 PC에서 압축해 복사합니다.

```bash
mkdir -p $SRC_DIR
cd $SRC_DIR
git clone https://github.com/DataDynamics-OSS/nifi-monitoring.git nifi-monitoring
# 또는: 다른 PC에서 tar czf nifi-monitoring.tgz nifi-monitoring → scp로 $SRC_DIR 에 복사 → tar xzf nifi-monitoring.tgz

ls $REPO                                 # exporter, deploy, docs ... 가 보이면 성공
```

### 1.6 시간대를 Asia/Seoul로 고정

이 가이드는 **모든 시간대를 `Asia/Seoul`(KST, UTC+9)로 고정**합니다. 서버마다 시간대가 다르면 알림 시각과 대시보드 시각을 맞춰 보기 어렵고, NiFi와 exporter의 시간대가 어긋나면 heartbeat 알림이 잘못 울립니다.

| 대상 | 설정 | 하는 단계 |
|---|---|---|
| 모니터링 서버 OS | `timedatectl set-timezone Asia/Seoul` | 지금 (1.6) |
| NiFi 서버 OS·NiFi | `Asia/Seoul` (NiFi 관리자에게 확인·요청) | 2.3 |
| nifi-exporter | `nifi.timezone: Asia/Seoul` | 3.3 |
| Grafana | 기본 시간대(1.8)와 NiFi 대시보드 6개(6.2)를 `Asia/Seoul`로 고정 | 1.8, 6.2 |

모니터링 서버의 시간대를 바꿉니다.

```bash
# [root]
timedatectl set-timezone Asia/Seoul
timedatectl | grep -E 'Time zone|synchronized'
# Time zone: Asia/Seoul (KST, +0900) 이 나오면 됩니다
# System clock synchronized: yes 도 확인합니다 (no 이면 NTP(chrony) 설정을 담당자에게 요청)
```

> 시각 자체가 틀리면(NTP 미동기) 시간대를 맞춰도 소용없습니다. 모니터링 서버와 NiFi 서버 모두 `System clock synchronized: yes`여야 합니다.
>
> Prometheus와 Alertmanager는 OS 시간대와 상관없이 **내부적으로 항상 UTC로 저장**합니다. 이것은 정상이며 바꿀 수 없습니다. 화면에서 보는 시각만 KST로 맞추면 됩니다(Grafana는 1.8·6.2에서 고정, Prometheus 화면은 상단의 **Use local time** 체크).

### 1.7 인터넷이 안 되는 서버라면 (폐쇄망)

아래 단계에서 내려받는 파일을 **인터넷이 되는 PC**에서 미리 받아 서버로 복사합니다.

| 파일 | 받는 곳 |
|---|---|
| `prometheus-2.53.4.linux-amd64.tar.gz` | https://github.com/prometheus/prometheus/releases/tag/v2.53.4 |
| `alertmanager-0.28.1.linux-amd64.tar.gz` | https://github.com/prometheus/alertmanager/releases/tag/v0.28.1 |
| Grafana rpm 또는 deb (11.6.0) | https://grafana.com/grafana/download/11.6.0?edition=oss |
| exporter의 Python 패키지 묶음 | [3.2의 "폐쇄망" 방법](#32-설치) 참고 |

받은 파일은 서버의 `$SRC_DIR/`에 둡니다. 이후 `curl -LO ...` 명령은 건너뛰고 `cd $SRC_DIR`만 하면 됩니다.

### 1.8 root 작업 모아 하기

OS가 위치를 정한 작업을 root로 한 번에 합니다. 이 단계가 끝나면 2~8단계는 실행 계정으로 진행합니다. root 셸에서 변수 파일부터 불러옵니다.

```bash
# [root]
source /appdata/nifi-monitoring/nifi-mon.env
echo $MON_HOME $RUN_USER          # /appdata/nifi-monitoring monitor 가 나와야 합니다
```

#### Python 3.11

```bash
python3 --version     # 3.11 이상이면 이 항목은 건너뜁니다
```

3.11보다 낮으면 설치합니다.

```bash
# [root]
# RHEL / Rocky 8·9
dnf install -y python3.11
# Ubuntu 22.04
apt update && apt install -y python3.11 python3.11-venv
# Ubuntu 24.04는 기본 python3(3.12)를 그대로 씁니다
apt update && apt install -y python3-venv
```

이후 명령의 `python3.11`은 설치된 실제 명령 이름(`python3.11` 또는 `python3`)으로 바꿔 씁니다.

#### 서비스 파일 등록 (systemd)

서버가 재부팅되거나 프로그램이 죽어도 자동으로 다시 뜨게 하는 파일입니다. 지금은 **파일만 등록**하고, 각 단계(3.4, 4.4, 5.3, 6.3, 7.2, 8.2)에서 설정을 마친 뒤 실행 계정이 켭니다. 쓰지 않을 선택 서비스(Provenance 조회, 알림 중계)는 파일만 있고 켜지 않으면 아무 영향이 없습니다.

```bash
# [root]
cat > $SYSTEMD_DIR/nifi-exporter.service <<EOF
[Unit]
Description=nifi-exporter (Apache NiFi Prometheus exporter)
Wants=network-online.target
After=network-online.target

[Service]
User=$EXPORTER_USER
Group=$EXPORTER_USER
ExecStart=$EXPORTER_HOME/venv/bin/nifi-exporter --config $EXPORTER_CONF/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > $SYSTEMD_DIR/prometheus.service <<EOF
[Unit]
Description=Prometheus
Wants=network-online.target
After=network-online.target

[Service]
User=$PROM_USER
Group=$PROM_USER
ExecStart=$BIN_DIR/prometheus \\
  --config.file=$PROM_CONF/prometheus.yml \\
  --storage.tsdb.path=$PROM_DATA \\
  --storage.tsdb.retention.time=15d \\
  --web.listen-address=0.0.0.0:9090
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

cat > $SYSTEMD_DIR/alertmanager.service <<EOF
[Unit]
Description=Alertmanager
Wants=network-online.target
After=network-online.target

[Service]
User=$AM_USER
Group=$AM_USER
ExecStart=$BIN_DIR/alertmanager \\
  --config.file=$AM_CONF/alertmanager.yml \\
  --storage.path=$AM_DATA \\
  --web.listen-address=0.0.0.0:9093 \\
  --cluster.listen-address=
ExecReload=/bin/kill -HUP \$MAINPID
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# (선택) 7단계 Provenance 조회 서비스
cat > $SYSTEMD_DIR/nifi-provenance-query.service <<EOF
[Unit]
Description=nifi-provenance-query
Wants=network-online.target
After=network-online.target

[Service]
User=$EXPORTER_USER
Group=$EXPORTER_USER
ExecStart=$EXPORTER_HOME/venv/bin/nifi-provenance-query --config $PROVQ_CONF/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# (선택) 8단계 알림 중계 서비스
cat > $SYSTEMD_DIR/nifi-alert-relay.service <<EOF
[Unit]
Description=nifi-alert-relay
Wants=network-online.target
After=network-online.target

[Service]
User=$EXPORTER_USER
Group=$EXPORTER_USER
EnvironmentFile=$RELAY_CONF/env
ExecStart=$EXPORTER_HOME/venv/bin/nifi-alert-relay --config $RELAY_CONF/config.yaml
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
grep -h -E '^(User|ExecStart)=' $SYSTEMD_DIR/{nifi-exporter,prometheus,alertmanager}.service
```

마지막 명령에서 `User=`가 실행 계정이고 `ExecStart=`의 경로가 모두 `/appdata/nifi-monitoring/...`이면 됩니다(변수가 빈 칸이면 변수 파일을 불러오지 않은 것입니다).

- Prometheus는 데이터를 15일 보관합니다(`--storage.tsdb.retention.time=15d`). 안정화 후 `30d`로 늘리려면 root가 이 파일을 고치고 `systemctl daemon-reload && systemctl restart prometheus` 합니다.
- Alertmanager의 `--cluster.listen-address=`(빈 값)은 한 대만 쓸 때 다중화 기능을 끄는 옵션입니다.

#### Grafana 패키지와 환경 파일

```bash
# [root]
cd $SRC_DIR
# RHEL / Rocky
curl -LO https://dl.grafana.com/oss/release/grafana-11.6.0-1.x86_64.rpm
dnf install -y ./grafana-11.6.0-1.x86_64.rpm

# Ubuntu
curl -LO https://dl.grafana.com/oss/release/grafana_11.6.0_amd64.deb
apt install -y ./grafana_11.6.0_amd64.deb
```

Grafana가 등록 파일을 `/etc/grafana/provisioning` 대신 `$GRAFANA_PROV`에서 읽게 하고, Prometheus 주소(`PROMETHEUS_URL`, 데이터소스 파일이 읽음)와 기본 시간대(새로 만드는 대시보드, Explore 화면 등)를 넣습니다. 아직 시작하지 않습니다(6.3).

```bash
# [root]
grep '^PROVISIONING_CFG_DIR' $GRAFANA_ENV      # 패키지 기본값 /etc/grafana/provisioning
sed -i "s#^PROVISIONING_CFG_DIR=.*#PROVISIONING_CFG_DIR=$GRAFANA_PROV#" $GRAFANA_ENV
echo 'PROMETHEUS_URL=http://localhost:9090' >> $GRAFANA_ENV
echo 'GF_DATE_FORMATS_DEFAULT_TIMEZONE=Asia/Seoul' >> $GRAFANA_ENV
grep -E '^(PROVISIONING_CFG_DIR|PROMETHEUS_URL|GF_DATE_FORMATS_DEFAULT_TIMEZONE)=' $GRAFANA_ENV
```

마지막 명령에서 세 줄이 나오고 첫 줄이 `PROVISIONING_CFG_DIR=/appdata/nifi-monitoring/grafana/provisioning`이면 됩니다.

> 이미 다른 용도로 쓰고 있는 Grafana라면 `PROVISIONING_CFG_DIR`은 바꾸지 않습니다(기존 등록 파일을 읽지 못하게 됩니다). 대신 6.2의 등록 파일 두 개를 root가 `/etc/grafana/provisioning/datasources/`와 `/etc/grafana/provisioning/dashboards/`에 복사합니다.

#### 서비스 제어 위임 (sudo, 권장)

실행 계정이 이 서비스들만 켜고 끄고 다시 읽게 합니다. 하지 않으면 3~8단계와 11장의 `sudo systemctl ...` 명령을 root가 대신 실행합니다. A(서비스별 계정)는 root로 설치하므로 건너뜁니다.

```bash
# [root]
SYSTEMCTL=$(command -v systemctl)
{
  printf 'Cmnd_Alias NIFI_MON_SVC ='
  sep=' '
  for svc in nifi-exporter nifi-provenance-query nifi-alert-relay prometheus alertmanager grafana-server; do
    for verb in start stop restart reload enable disable; do
      printf '%s%s %s %s' "$sep" "$SYSTEMCTL" "$verb" "$svc"
      sep=', '
    done
  done
  printf '\n%s ALL=(root) NOPASSWD: NIFI_MON_SVC\n' "$RUN_USER"
} > /etc/sudoers.d/nifi-monitoring
chmod 440 /etc/sudoers.d/nifi-monitoring
visudo -cf /etc/sudoers.d/nifi-monitoring      # parsed OK 가 나와야 합니다
sudo -l -U $RUN_USER | grep -c systemctl       # 1 이상이면 됩니다
```

- 허용한 명령의 형태는 `sudo systemctl <start|stop|restart|reload|enable|disable> <서비스 하나>`뿐입니다. 서비스 여러 개를 한 줄에 쓰거나 `enable --now`처럼 옵션을 붙이면 비밀번호를 묻습니다. 이 문서는 서비스마다 한 줄씩 적었습니다.
- 상태 보기(`systemctl status`, `systemctl is-active`)와 로그 보기(`journalctl -u`, 1.3에서 `systemd-journal` 그룹에 넣음)는 sudo 없이 됩니다.

#### 방화벽

사용자 PC에서 접속하는 포트만 엽니다. Grafana(3000)는 필수, Provenance 조회(9104)는 7단계를 할 때만 엽니다.

```bash
# [root]
# RHEL / Rocky
firewall-cmd --permanent --add-port=3000/tcp && firewall-cmd --reload
firewall-cmd --permanent --add-port=9104/tcp && firewall-cmd --reload     # (선택) 7단계
# Ubuntu (ufw 사용 시)
ufw allow 3000/tcp
ufw allow 9104/tcp                                                        # (선택) 7단계
```

이제 root 셸을 닫고 실행 계정(`sudo -iu monitor`)으로 2단계부터 진행합니다.

---

## 2. NiFi 접속 준비

exporter가 NiFi에 접속할 방법을 준비합니다. **NiFi 유형에 따라 할 일이 다릅니다.** 인증·권한이 없는 NiFi는 준비할 것이 거의 없습니다.

### 2.1 유형 확인

[설치 전 체크리스트](#설치-전-체크리스트)의 **B0**(NiFi 유형)을 먼저 정합니다.

| 유형 | 2.2에서 할 일 | exporter `nifi.auth.mode` |
|---|---|---|
| ① 인증·권한 없음 (`http://`, 로그인 없음) | 접속 확인만 | `none` |
| ② Single User (`https://`, 관리자 하나) | 관리자 아이디·비밀번호 받기, 토큰 확인 | `bearer` |
| ③ LDAP·Kerberos (`https://`, 사용자별 정책) | 전용 계정 + 정책 4개, 토큰 확인 | `bearer` |
| ④ 인증서 (`https://`, 사용자별 정책) | 인증서 DN 사용자 + 정책 4개 | `mtls` |

### 2.2 유형별 준비

#### ① 인증·권한 없음

계정도 정책도 만들 필요가 없습니다. NiFi에 사용자·정책 기능이 꺼져 있어, 모든 요청이 `anonymous`로 처리되고 모든 읽기가 허용됩니다.

**확인**: 모니터링 서버에서 익명으로 읽히는지 봅니다.

```bash
curl -s http://nifi.example.com:8080/nifi-api/flow/current-user | grep -o '"identity":"[^"]*"'
# "identity":"anonymous" 가 나오면 됩니다
curl -s -o /dev/null -w "%{http_code}\n" http://nifi.example.com:8080/nifi-api/flow/process-groups/root/status
# 200 이 나오면 exporter가 수집할 수 있습니다
```

> 이 유형의 NiFi는 접속만 되면 누구나 플로우를 바꿀 수 있습니다. exporter는 조회만 하지만, 모니터링 서버도 NiFi를 바꿀 수 있는 위치에 있다는 점을 기억하고 서버 접근을 관리합니다.

[2.3](#23-nifi-시간대-asiaseoul-확인)으로 갑니다.

#### ② Single User (인증만 있고 권한 설정 없음)

NiFi 2.x를 기본값으로 설치하면 이 구성입니다. 사용자는 관리자 하나뿐이고 **정책(Policies) 메뉴가 없습니다.** 따라서 읽기 전용 계정을 만들 수 없고, exporter는 관리자 아이디·비밀번호를 그대로 씁니다.

1. NiFi 관리자에게 관리자 아이디와 비밀번호를 받습니다. 비밀번호는 NiFi에 해시로만 저장되므로 파일에서 찾을 수 없습니다. 모르면 NiFi 관리자가 `nifi.sh set-single-user-credentials <아이디> <비밀번호>`로 다시 정하고 NiFi를 재시작해야 합니다(**NiFi UI 사용자 모두에게 영향**).
2. 비밀번호를 바꿀 때 모니터링 담당자에게도 알려 달라고 합의합니다(바뀌면 exporter가 `401`로 수집을 멈춥니다).
3. 아래 "확인 (bearer)"로 토큰이 발급되는지 봅니다. `nifi-monitor` 자리에 관리자 아이디를 넣습니다.

#### ③ LDAP·Kerberos / ④ 인증서 (인증·권한 모두 있음)

exporter가 NiFi를 **읽기만** 하도록 전용 계정을 준비합니다. NiFi 관리자 권한이 필요합니다.

1. NiFi UI 오른쪽 위 메뉴(☰) → **Users** → 사용자 추가
   - ③ LDAP·Kerberos: LDAP 등에 `nifi-monitor` 계정을 만들고 같은 이름으로 NiFi 사용자를 추가합니다.
   - ④ 인증서: 인증서의 DN(예: `CN=nifi-monitor`)을 사용자 이름으로 추가합니다.
2. 메뉴(☰) → **Policies**에서 다음 4개 정책에 `nifi-monitor`를 추가합니다.

   | 정책 (Access Policies 화면) | 권한 |
   |---|---|
   | view the user interface (`/flow`) | view |
   | access the controller (`/controller`) | view |
   | view system diagnostics (`/system`) | view |
   | 루트 Process Group 선택 → 왼쪽 Operate 패널의 열쇠 아이콘 → **view the component** | view |

   이 4개면 충분합니다. **modify 권한은 주지 않습니다.**

   사용자를 추가하고 정책을 주지 않으면 로그인은 되지만 모든 조회가 `403`으로 실패합니다. "인증은 되는데 권한 설정이 안 된" 상태이므로 정책 4개를 꼭 확인합니다.

#### 공통 (②·③·④ HTTPS)

- exporter가 NiFi 노드 이름이 아닌 주소(로드밸런서, IP 등)로 접속한다면 NiFi의 `nifi.properties`에 있는 `nifi.web.proxy.host`에 그 주소를 추가해 달라고 NiFi 관리자에게 요청합니다. 빠뜨리면 `400 Invalid host header` 오류가 납니다.

**확인 (bearer, ②·③)**: 모니터링 서버에서 토큰이 발급되는지 봅니다.

```bash
curl -k -s -X POST https://nifi.example.com:8443/nifi-api/access/token \
  -d 'username=nifi-monitor' -d 'password=<비밀번호>' | head -c 40; echo
```

`eyJ...`로 시작하는 긴 문자열이 나오면 성공입니다.

**확인 (mtls, ④)**: 인증서로 누구로 보이는지 봅니다.

```bash
curl -s --cacert ca.pem --cert client.pem --key client-key.pem \
  https://nifi.example.com:8443/nifi-api/flow/current-user | grep -o '"identity":"[^"]*"'
# "identity":"CN=nifi-monitor..." 처럼 등록한 DN이 나오면 됩니다
```

### 2.3 NiFi 시간대 (Asia/Seoul) 확인

**중요한 단계입니다.** exporter는 `nifi.timezone: Asia/Seoul`로 고정합니다. NiFi도 KST로 동작해야 heartbeat 시각이 맞고, 아니면 "heartbeat 지연" 알림이 계속 잘못 울립니다.

```bash
# ②·③ bearer: 위에서 받은 토큰을 씁니다
TOKEN=$(curl -k -s -X POST https://nifi.example.com:8443/nifi-api/access/token \
  -d 'username=nifi-monitor' -d 'password=<비밀번호>')
curl -k -s -H "Authorization: Bearer $TOKEN" https://nifi.example.com:8443/nifi-api/flow/about \
  | grep -o '"timezone":"[^"]*"'

# ① 인증·권한 없음(http)
curl -s http://nifi.example.com:8080/nifi-api/flow/about | grep -o '"timezone":"[^"]*"'
```

| 결과 | 할 일 |
|---|---|
| `"timezone":"KST"` | 정상입니다. 다음 단계로 갑니다 |
| 그 밖의 값 (`UTC`, `EDT` 등) | NiFi가 KST가 아닙니다. 아래처럼 NiFi 쪽을 Asia/Seoul로 바꾸도록 NiFi 관리자에게 요청합니다 |

**NiFi를 Asia/Seoul로 바꾸는 방법** (NiFi 관리자 작업, 모든 노드, NiFi 재시작 필요)

1. NiFi 서버 OS: `timedatectl set-timezone Asia/Seoul`
2. NiFi JVM도 확실히 고정하려면 `conf/bootstrap.conf`에 한 줄을 추가합니다(번호 `N`은 기존 `java.arg.` 번호와 겹치지 않게). CFM은 Cloudera Manager의 NiFi **구성**에서 Java 옵션에 `-Duser.timezone=Asia/Seoul`을 넣습니다.

   ```properties
   java.arg.N=-Duser.timezone=Asia/Seoul
   ```

3. NiFi를 재시작하고 위 명령으로 `"timezone":"KST"`가 나오는지 다시 확인합니다.

> NiFi 시간대를 당장 바꿀 수 없다면, 바꿀 때까지만 예외로 exporter의 `nifi.timezone`에 NiFi의 실제 시간대(예: `EDT`·`EST`면 `America/New_York`, `UTC`면 `UTC`)를 넣습니다. 이 값은 heartbeat 시각을 해석하는 데만 쓰이므로, 대시보드·알림 시각은 그대로 KST로 보입니다. NiFi를 KST로 바꾼 뒤 `Asia/Seoul`로 되돌리고 `sudo systemctl restart nifi-exporter` 합니다.

---

## 3. nifi-exporter 설치

### 3.1 Python 확인

```bash
python3.11 --version     # 3.11 이상이 나오면 됩니다 (Ubuntu 24.04는 python3 --version)
```

없으면 root에게 [1.8](#18-root-작업-모아-하기)의 Python 설치를 요청합니다. 이후 명령의 `python3.11`은 실제 명령 이름(`python3.11` 또는 `python3`)으로 바꿔 씁니다.

### 3.2 설치

**인터넷이 되는 서버**

```bash
python3.11 -m venv $EXPORTER_HOME/venv
$EXPORTER_HOME/venv/bin/pip install --upgrade pip
$EXPORTER_HOME/venv/bin/pip install $REPO/exporter
```

**폐쇄망 서버** — 인터넷이 되는 PC(같은 OS·같은 Python 버전 권장)에서 패키지를 묶어 옵니다.

```bash
# (인터넷 PC) 저장소의 exporter 디렉터리에서
python3.11 -m pip wheel ./exporter -w wheels      # wheels/ 에 .whl 파일들이 생깁니다
tar czf nifi-exporter-wheels.tgz wheels
# → 서버의 $SRC_DIR 로 복사

# (서버)
cd $SRC_DIR && tar xzf nifi-exporter-wheels.tgz
python3.11 -m venv $EXPORTER_HOME/venv
$EXPORTER_HOME/venv/bin/pip install --no-index --find-links $SRC_DIR/wheels nifi-exporter
```

**확인**

```bash
$EXPORTER_HOME/venv/bin/nifi-exporter --version     # 0.1.0 같은 버전이 나오면 성공
```

### 3.3 설정 파일 만들기

```bash
mkdir -p $EXPORTER_CONF
cp $REPO/exporter/config/nifi-exporter.example.yaml $EXPORTER_CONF/config.yaml
sed -i "s#/etc/nifi-exporter/#$EXPORTER_CONF/#g" $EXPORTER_CONF/config.yaml   # 파일 속 경로(Docker 기준)를 내 경로로
vi $EXPORTER_CONF/config.yaml        # 편집기는 편한 것을 씁니다 (nano 등)
```

반드시 바꿀 값입니다. 나머지는 기본값 그대로 두면 됩니다.

| 키 | 넣을 값 | 예 |
|---|---|---|
| `nifi.base_url` | NiFi 주소 (노드 하나 또는 로드밸런서) | `https://nifi.example.com:8443` |
| `nifi.cluster_name` | 이 클러스터를 부를 짧은 이름. **4·6단계에서 같은 값을 다시 씁니다** | `prod-nifi` |
| `nifi.timezone` | **`Asia/Seoul` 고정** (예시 파일에 이미 들어 있음, 바꾸지 않음). 예외는 [2.3](#23-nifi-시간대-asiaseoul-확인) 참고 | `Asia/Seoul` |
| `nifi.tls.ca_file` | NiFi 서버 인증서의 CA 파일 (HTTPS일 때) | `/appdata/nifi-monitoring/nifi-exporter/conf/ca.pem` |
| `nifi.auth` | 인증 방식별로 아래 표 | |

인증 방식별 `nifi.auth` 작성법:

```yaml
# (1) bearer — 아이디/비밀번호 (② Single User는 관리자 아이디, ③은 전용 계정)
  auth:
    mode: bearer
    username: nifi-monitor
    password_file: /appdata/nifi-monitoring/nifi-exporter/conf/password

# (2) mtls — 클라이언트 인증서 (④)
  auth:
    mode: mtls
    cert_file: /appdata/nifi-monitoring/nifi-exporter/conf/client.pem
    key_file: /appdata/nifi-monitoring/nifi-exporter/conf/client-key.pem

# (3) none — ① 인증·권한 없는 http:// NiFi (base_url도 http:// 로, tls 절은 무시됩니다)
  auth: { mode: none }
```

> YAML은 **들여쓰기(공백 2칸)**가 중요합니다. 탭 문자를 쓰지 않습니다.

비밀번호와 인증서 파일을 넣고 권한을 잠급니다.

```bash
# bearer: 비밀번호 파일 (줄바꿈 없이 저장)
printf '%s' '<nifi-monitor 비밀번호>' > $EXPORTER_CONF/password

# HTTPS: NiFi 관리자에게 받은 CA 인증서 (PEM 형식)
cp ca.pem $EXPORTER_CONF/ca.pem
# mtls: 클라이언트 인증서와 키
cp client.pem client-key.pem $EXPORTER_CONF/

chown -R $EXPORTER_USER: $EXPORTER_CONF      # A(서비스별 계정)일 때 소유자를 서비스 계정으로 (B는 바뀌지 않음)
chmod 700 $EXPORTER_CONF
chmod 600 $EXPORTER_CONF/*
```

> CA 파일을 구하기 어렵다면 임시로 `nifi.tls.insecure_skip_verify: true`로 시험할 수 있습니다. **운영에서는 쓰지 않습니다.**

**(권장) `/metrics` 비밀번호 걸기** — `/metrics`에는 큐·Processor 이름이 보이므로 비밀번호를 겁니다. 설정 파일 맨 아래 `server:` 절의 주석을 풀어 다음처럼 만듭니다.

```yaml
server:
  listen: 0.0.0.0:9103
  log_level: INFO
  log_format: json
  log_bulletin_messages: false
  basic_auth:
    username: prometheus
    password_file: /appdata/nifi-monitoring/nifi-exporter/conf/metrics-password
```

```bash
openssl rand -hex 16 > $EXPORTER_CONF/metrics-password   # 무작위 비밀번호 생성
chown $EXPORTER_USER: $EXPORTER_CONF/metrics-password
chmod 600 $EXPORTER_CONF/metrics-password
cat $EXPORTER_CONF/metrics-password                       # 4단계에서 같은 값을 씁니다
```

**확인**

```bash
$EXPORTER_HOME/venv/bin/nifi-exporter --config $EXPORTER_CONF/config.yaml --check-config
# A(서비스별 계정): sudo -u $EXPORTER_USER $EXPORTER_HOME/venv/bin/nifi-exporter --config $EXPORTER_CONF/config.yaml --check-config
```

오류 없이 끝나면 성공입니다. 오류가 나면 메시지에 나온 키를 고칩니다.

### 3.4 서비스 시작

서비스 파일은 1.8에서 root가 등록했습니다. 부팅 때 자동 시작하도록 켜고 시작합니다.

```bash
sudo systemctl enable nifi-exporter
sudo systemctl start nifi-exporter
```

**확인**

```bash
systemctl status nifi-exporter --no-pager          # active (running) 이면 정상
curl -s localhost:9103/readyz                      # 30초쯤 뒤 ready 가 나오면 수집 성공
# 비밀번호를 걸었다면 -u 옵션을 붙입니다
curl -s -u prometheus:$(cat $EXPORTER_CONF/metrics-password) localhost:9103/metrics \
  | grep nifi_exporter_collector_success
```

마지막 명령에서 collector 6개(`cluster`, `flow`, `diagnostics`, `bulletin`, `controller`, `topology`)가 모두 `1.0`이면 성공입니다. `0.0`이 있으면 로그를 봅니다.

```bash
journalctl -u nifi-exporter -n 50 --no-pager
```

> `topology`는 처음 몇 분 동안 값이 없을 수 있습니다(5분 주기).
> **클러스터 하나에 exporter는 하나만** 운영합니다. 두 대에 설치하면 알림이 동작하지 않습니다.

### 3.5 (대안) 설치 없이 스크립트로 실행

pip·venv 없이 **압축 파일 하나**를 풀고 `bin/start.sh`로 실행하는 방법입니다. 3.2~3.4 대신 씁니다.
서버에는 Python 3.11 이상만 있으면 되고, 폐쇄망에도 tar 파일 하나만 옮기면 됩니다.

**묶음 만들기** (저장소가 있는 PC, 인터넷 필요)

```bash
cd $REPO/exporter
PYTHON=python3.11 make dist      # → dist/nifi-exporter-0.1.0.tar.gz (약 1.5MB)
```

빌드 Python은 서버의 Python보다 높지 않게(3.11 권장) 둡니다. 의존 라이브러리를 빌드 Python 기준으로 고르기 때문입니다.

**풀기와 구성**

```bash
tar xzf nifi-exporter-0.1.0.tar.gz -C $MON_HOME
ln -sfn $MON_HOME/nifi-exporter-0.1.0 $MON_HOME/nifi-exporter-dist
chown -R $EXPORTER_USER: $MON_HOME/nifi-exporter-0.1.0     # A(서비스별 계정)일 때만 바뀝니다
```

```
/appdata/nifi-monitoring/nifi-exporter-dist/
├── bin/        start.sh stop.sh restart.sh status.sh check-config.sh (common.sh는 공통 함수)
├── config/     env.sh, nifi-exporter.yaml, provenance-query.yaml, alert-relay.yaml, secrets/
├── logs/       서비스별 로그(.log), 시작 실패 출력(.out), pid 파일
├── src/        nifi_exporter 소스
└── lib/        의존 라이브러리(httpx, prometheus_client, PyYAML 등)
```

**설정** — `config/nifi-exporter.yaml`은 3.3과 같은 내용이고, 경로가 이미 배포 디렉토리 기준으로 바뀌어 있습니다.
비밀번호·인증서는 `config/secrets/`에 둡니다(`password`, `ca.pem`, `client.pem`, `client-key.pem`).
로그 파일 경로는 yaml에서 정합니다.

```yaml
server:
  log_file: logs/nifi-exporter.log   # 상대 경로는 배포 디렉토리 기준. 지우면 logs/exporter.out에 씁니다
  log_max_size: 50MB                 # 넘으면 .1 ~ .5로 돌립니다
  log_backups: 5
```

`config/env.sh`에서 Python 경로(`PYTHON`)와 함께 돌릴 서비스(`SERVICES="exporter provenance relay"`)를 정합니다.

**실행** — 실행 계정으로 합니다(root는 거부합니다). A(서비스별 계정)면 각 명령 앞에 `sudo -u $EXPORTER_USER`를 붙입니다.

```bash
cd $MON_HOME/nifi-exporter-dist
bin/check-config.sh        # exporter: 정상 (...) 이면 OK
bin/start.sh               # SERVICES 전체, 또는 bin/start.sh exporter relay
bin/status.sh              # exporter  RUNNING  pid=... healthz=ok
bin/stop.sh
bin/restart.sh
```

| 스크립트 | 하는 일 | 종료 코드 |
|---|---|---|
| `start.sh` | 설정 검사 → 포트 중복 확인 → 백그라운드 실행 → `/healthz` 200 확인. 이미 실행 중이면 그대로 둡니다 | 실패 1 |
| `stop.sh` | SIGTERM, `STOP_TIMEOUT`(30초) 뒤에도 남으면 SIGKILL | 0 |
| `restart.sh` | stop 후 start | start와 같음 |
| `status.sh` | pid·실행 시간·listen·`/healthz`·로그 위치 | 0 정상, 1 healthz 실패, 3 멈춤 |
| `check-config.sh` | `--check-config`로 설정·비밀번호 파일·`${ENV}` 확인 | 오류 1 |

**부팅 시 자동 시작·자동 재시작** — systemd 대신 실행 계정의 crontab을 씁니다(root 작업 없음). crontab에는 변수를 쓸 수 없으므로 실제 경로를 적습니다.

```bash
crontab -e                 # A(서비스별 계정)는 sudo -u $EXPORTER_USER crontab -e
@reboot /appdata/nifi-monitoring/nifi-exporter-dist/bin/start.sh
*/5 * * * * /appdata/nifi-monitoring/nifi-exporter-dist/bin/status.sh >/dev/null || /appdata/nifi-monitoring/nifi-exporter-dist/bin/start.sh >/dev/null
```

**업그레이드** — 새 묶음을 옆에 풀고 `config/`를 복사한 뒤 링크를 바꿉니다. 되돌릴 때는 링크만 원래대로 돌립니다.

```bash
tar xzf nifi-exporter-0.2.0.tar.gz -C $MON_HOME
cp -a $MON_HOME/nifi-exporter-dist/config/. $MON_HOME/nifi-exporter-0.2.0/config/
$MON_HOME/nifi-exporter-dist/bin/stop.sh all
ln -sfn $MON_HOME/nifi-exporter-0.2.0 $MON_HOME/nifi-exporter-dist
$MON_HOME/nifi-exporter-dist/bin/start.sh all
```

> 같은 디렉토리에서는 중복 실행을 막지만, 다른 서버나 다른 디렉토리에 띄운 exporter는 막지 못합니다.
> **클러스터 하나에 exporter는 하나만** 운영합니다.

---

## 4. Prometheus 설치

### 4.1 내려받기와 설치

```bash
cd $SRC_DIR
curl -LO https://github.com/prometheus/prometheus/releases/download/v2.53.4/prometheus-2.53.4.linux-amd64.tar.gz
tar xzf prometheus-2.53.4.linux-amd64.tar.gz

mkdir -p $BIN_DIR $PROM_CONF/rules $PROM_CONF/secrets $PROM_DATA
cp prometheus-2.53.4.linux-amd64/prometheus prometheus-2.53.4.linux-amd64/promtool $BIN_DIR/
```

**확인**

```bash
prometheus --version    # prometheus, version 2.53.4 ($BIN_DIR가 PATH에 있어 경로 없이 부릅니다)
```

### 4.2 설정 파일 복사

```bash
cp $REPO/deploy/prometheus/prometheus.yml $PROM_CONF/prometheus.yml
cp $REPO/deploy/prometheus/rules/*.yml    $PROM_CONF/rules/
sed -i "s#/etc/prometheus/#$PROM_CONF/#g" $PROM_CONF/prometheus.yml   # 파일 속 경로(Docker 기준)를 내 경로로
```

### 4.3 설정 파일 고치기

`vi $PROM_CONF/prometheus.yml`로 열어 아래 표대로 고칩니다. 저장소의 파일은 Docker 환경 기준이라 주소가 서비스 이름(`alertmanager`, `nifi-exporter`)으로 되어 있으므로, 한 서버에 설치할 때는 `localhost`로 바꿉니다.

| 위치 | 원래 값 | 바꿀 값 |
|---|---|---|
| `alerting` → `targets` | `alertmanager:9093` | `localhost:9093` |
| `nifi-exporter` job → `targets` | `nifi-exporter:9103` | `localhost:9103` |
| `nifi-exporter` job → `labels.cluster` | `prod-nifi` | 3.3의 `nifi.cluster_name`과 **똑같은 값** |
| `nifi-exporter` job → `basic_auth` | | 3.3에서 비밀번호를 걸었으면 그대로 둠, 안 걸었으면 `basic_auth:` 3줄 삭제 |

그리고 쓰지 않는 job을 **지웁니다**(`- job_name:` 줄부터 다음 `- job_name:` 앞까지).

| job | 지우는 경우 |
|---|---|
| `nifi-alert-relay` | 8단계(알림 중계)를 하지 않으면 지웁니다. 나중에 다시 추가할 수 있습니다 |
| `nifi-builtin` | 처음에는 **지우기를 권합니다.** bearer 인증이거나 NiFi 주소가 로드밸런서이면 쓸 수 없습니다. 노드별 큐 분해 화면만 비고 나머지는 모두 동작합니다 |
| `node` | NiFi 서버에 node_exporter가 없으면 지웁니다 |

고친 뒤 `nifi-exporter` job은 대략 이렇게 생깁니다.

```yaml
  - job_name: nifi-exporter
    scrape_interval: 15s
    metrics_path: /metrics
    honor_labels: true
    basic_auth:
      username: prometheus
      password_file: /appdata/nifi-monitoring/prometheus/conf/secrets/nifi-exporter-metrics-password
    static_configs:
      - targets: ["localhost:9103"]
        labels:
          cluster: prod-nifi
```

exporter `/metrics` 비밀번호를 걸었다면 같은 비밀번호를 Prometheus 쪽에도 둡니다.

```bash
cp $EXPORTER_CONF/metrics-password $PROM_CONF/secrets/nifi-exporter-metrics-password
chown -R $PROM_USER: $PROM_CONF $PROM_DATA      # A(서비스별 계정)일 때만 바뀝니다
chmod 700 $PROM_CONF/secrets
chmod 600 $PROM_CONF/secrets/*
```

**확인**

```bash
cd $PROM_CONF
promtool check config prometheus.yml       # SUCCESS 가 나와야 합니다
promtool check rules rules/*.yml
# 저장소의 규칙 테스트도 돌려 볼 수 있습니다
cd $REPO/deploy/prometheus && promtool test rules tests/*_test.yml
```

### 4.4 서비스 시작

```bash
sudo systemctl enable prometheus
sudo systemctl start prometheus
```

- 데이터는 15일 보관합니다. 기간은 1.8의 서비스 파일(`--storage.tsdb.retention.time`)에서 root가 바꿉니다.
- 설정을 고친 뒤에는 `sudo systemctl reload prometheus`로 반영합니다(재시작 불필요).

**확인**

```bash
systemctl status prometheus --no-pager
curl -s 'localhost:9090/api/v1/query?query=up' | grep -o '"job":"[^"]*"[^]]*"value":\[[^]]*\]'
```

`"job":"nifi-exporter"` 줄의 값이 `"1"`이면 성공입니다. 브라우저로 `http://<모니터링 서버>:9090/targets`를 열어 모든 대상이 **UP**인지 봐도 됩니다(아직 Alertmanager가 없어 상단에 경고가 보일 수 있습니다. 5단계에서 해결됩니다).

---

## 5. Alertmanager 설치

### 5.1 내려받기와 설치

```bash
cd $SRC_DIR
curl -LO https://github.com/prometheus/alertmanager/releases/download/v0.28.1/alertmanager-0.28.1.linux-amd64.tar.gz
tar xzf alertmanager-0.28.1.linux-amd64.tar.gz

mkdir -p $BIN_DIR $AM_CONF/templates $AM_DATA
cp alertmanager-0.28.1.linux-amd64/alertmanager alertmanager-0.28.1.linux-amd64/amtool $BIN_DIR/
cp $REPO/deploy/alertmanager/alertmanager.yml       $AM_CONF/
cp $REPO/deploy/alertmanager/templates/nifi.tmpl    $AM_CONF/templates/
sed -i "s#/etc/alertmanager/#$AM_CONF/#g" $AM_CONF/alertmanager.yml   # 파일 속 경로(Docker 기준)를 내 경로로
```

### 5.2 알림 받을 곳 정하기

`$AM_CONF/alertmanager.yml`에는 수신처 4개가 있습니다. **쓰는 것만 채우고, 안 쓰는 것은 정리합니다.**

| 수신처 | 무엇을 받나 | 채울 값 |
|---|---|---|
| `ops-slack` | 모든 warning, critical | Slack Incoming Webhook URL, 채널명 `#nifi-alerts` |
| `ops-pager` | critical | 당직 시스템 webhook `url` |
| `platform-team` | 수집 장애(exporter) | `to:` 메일 주소, `global`의 `smtp_*` |
| `custom-relay` | 모든 알림을 사내 HTTP API로 | 8단계에서 설정 |

**Slack** — 웹훅 URL은 YAML에 직접 쓰지 않고 파일에 넣습니다.

```bash
printf '%s' 'https://hooks.slack.com/services/XXX/YYY/ZZZ' > $AM_CONF/slack_webhook
```

**메일** — `global` 절의 `smtp_smarthost`, `smtp_from`, `smtp_auth_username`을 사내 메일 서버 값으로 바꾸고 비밀번호는 파일에 넣습니다.

```bash
printf '%s' '<SMTP 비밀번호>' > $AM_CONF/smtp_password
```

**호출기** — `ops-pager`의 `url: https://oncall.example.com/webhook/nifi`를 실제 주소로 바꿉니다. 호출기가 없으면 다음 두 곳을 지웁니다.
- `routes:` 안의 `- matchers: [severity="critical"]` / `receiver: ops-pager` / `continue: true` 3줄
- `receivers:` 안의 `- name: ops-pager` 블록

**알림 중계를 쓰지 않으면**(8단계 생략) 다음 두 곳을 지웁니다.
- `routes:` 맨 앞의 `- receiver: custom-relay` / `continue: true` 2줄
- `receivers:` 안의 `- name: custom-relay` 블록

> 아무 수신처도 아직 정하지 못했다면 Slack만 먼저 채우고 시작하는 것이 가장 간단합니다. 메일을 안 쓰더라도 `platform-team`이 기본 경로에 있으므로, 쓰지 않을 때는 `component="exporter"` 경로의 `receiver: platform-team`을 `ops-slack`으로 바꾸고 `platform-team` 블록을 지웁니다.

권한을 정리합니다.

```bash
chown -R $AM_USER: $AM_CONF $AM_DATA      # A(서비스별 계정)일 때만 바뀝니다
chmod 700 $AM_CONF
chmod 600 $AM_CONF/slack_webhook $AM_CONF/smtp_password 2>/dev/null
```

**확인**

```bash
amtool check-config $AM_CONF/alertmanager.yml    # SUCCESS 가 나와야 합니다
```

### 5.3 서비스 시작

```bash
sudo systemctl enable alertmanager
sudo systemctl start alertmanager
```

**확인** — 시험 알림을 하나 보내 Slack(또는 메일)에 오는지 봅니다.

```bash
systemctl status alertmanager --no-pager
amtool --alertmanager.url=http://localhost:9093 alert add \
  alertname=GuideTest severity=warning cluster=prod-nifi \
  --annotation=summary="설치 시험 알림입니다"
```

30초쯤 뒤 알림이 도착하면 성공입니다. 오지 않으면 `journalctl -u alertmanager -n 50 --no-pager`에서 전송 오류를 봅니다. 시험 알림은 5분 뒤 저절로 해소됩니다.

Prometheus와 연결됐는지도 봅니다.

```bash
curl -s localhost:9090/api/v1/alertmanagers | grep -o '"url":"[^"]*"'   # localhost:9093 이 보이면 연결됨
```

---

## 6. Grafana 설치

### 6.1 설치 확인

Grafana 패키지와 환경 파일은 1.8에서 root가 준비했습니다.

```bash
grep -E '^(PROVISIONING_CFG_DIR|PROMETHEUS_URL|GF_DATE_FORMATS_DEFAULT_TIMEZONE)=' $GRAFANA_ENV
# PROVISIONING_CFG_DIR=/appdata/nifi-monitoring/grafana/provisioning 를 포함해 세 줄이 나오면 됩니다
```

### 6.2 데이터소스와 대시보드 넣기

Grafana가 시작할 때 Prometheus 연결과 NiFi 대시보드 6개를 자동으로 등록하게 합니다. 등록 파일은 1.8에서 정한 `$GRAFANA_PROV`에 둡니다.

```bash
mkdir -p $GRAFANA_PROV/datasources $GRAFANA_PROV/dashboards $GRAFANA_PROV/plugins $GRAFANA_PROV/alerting
cp $REPO/deploy/grafana/provisioning/datasources/prometheus.yaml $GRAFANA_PROV/datasources/nifi-prometheus.yaml
cp $REPO/deploy/grafana/provisioning/dashboards/nifi.yaml        $GRAFANA_PROV/dashboards/nifi.yaml
sed -i "s#/var/lib/grafana/dashboards/nifi#$GRAFANA_DASH#" $GRAFANA_PROV/dashboards/nifi.yaml   # 대시보드 위치를 내 경로로

mkdir -p $GRAFANA_DASH
cp $REPO/deploy/grafana/dashboards/*.json $GRAFANA_DASH/
# 대시보드 시간대를 사용자 브라우저 기준(browser)에서 Asia/Seoul 고정으로 바꿉니다
sed -i 's/"timezone": "browser"/"timezone": "Asia\/Seoul"/' $GRAFANA_DASH/*.json
grep -o '"timezone": "[^"]*"' $GRAFANA_DASH/*.json   # 6개 모두 Asia/Seoul 이면 됩니다
chmod -R a+rX $MON_HOME/grafana                      # grafana 계정이 읽을 수 있게 합니다
```

> 저장소의 대시보드는 사용자 PC의 시간대(`browser`)로 시각을 보여 줍니다. 위 `sed` 명령은 **서버에 복사한 파일만** `Asia/Seoul`로 바꾸므로, 대시보드를 다시 복사할 때(7.3, 11.1)마다 이 명령을 다시 실행합니다.

데이터소스 파일은 Prometheus 주소를 환경변수 `PROMETHEUS_URL`에서 읽습니다. 이 값과 Grafana 기본 시간대(`GF_DATE_FORMATS_DEFAULT_TIMEZONE=Asia/Seoul`)는 1.8에서 환경 파일에 넣었습니다.

> 이미 다른 Prometheus 데이터소스가 "기본(isDefault)"으로 등록된 Grafana라면 `nifi-prometheus.yaml`의 `isDefault: true`를 `false`로 바꿉니다. 대시보드는 uid `prometheus`로 찾으므로 기본 여부와 상관없이 동작합니다.

### 6.3 시작

```bash
sudo systemctl enable grafana-server
sudo systemctl start grafana-server
```

**확인**

1. 브라우저로 `http://<모니터링 서버>:3000` 접속 → `admin` / `admin` 로그인 → 새 비밀번호 설정
2. 왼쪽 메뉴 **Dashboards** → **NiFi** 폴더에 대시보드 6개(개요, 프로세스 그룹, 프로세서, 큐, 장애 분석, JVM·스레드)가 보이면 성공
3. **NiFi / 개요**를 열어 맨 위 수집기 상태가 모두 정상이고 노드 수가 보이는지 확인

접속이 안 되면 1.8의 방화벽(3000 포트)을 root가 열었는지 확인합니다.

> 대시보드는 **읽기 전용**으로 올라갑니다. 화면에서 고쳐도 저장되지 않습니다. 고치는 방법은 [deploy/grafana/README.md](deploy/grafana/README.md)에 있습니다.

**Grafana도 하나의 계정으로 실행하려면** (1.3의 B, 회사 규칙상 꼭 필요할 때만)

패키지의 서비스 파일은 고치지 않고, 덮어쓰기 파일(drop-in)로 실행 계정만 바꿉니다.

```bash
# [root]
mkdir -p $SYSTEMD_DIR/grafana-server.service.d
cat > $SYSTEMD_DIR/grafana-server.service.d/run-as-monitor.conf <<'EOF'
[Service]
User=monitor
Group=monitor
EOF

chown -R monitor:monitor /var/lib/grafana /var/log/grafana
chgrp -R monitor /etc/grafana          # 설정 파일을 읽을 수 있게 합니다
systemctl daemon-reload
systemctl restart grafana-server
```

- Grafana 패키지를 업데이트한 뒤 화면이 안 뜨면 위 `chown`과 `chgrp` 두 줄을 다시 실행합니다.
- 되돌리려면 drop-in 디렉터리를 지우고 소유자를 `grafana`로 되돌린 뒤 재시작합니다.

  ```bash
  # [root]
  rm -r $SYSTEMD_DIR/grafana-server.service.d
  chown -R grafana:grafana /var/lib/grafana /var/log/grafana
  chgrp -R grafana /etc/grafana
  systemctl daemon-reload && systemctl restart grafana-server
  ```

---

## 7. (선택) Provenance 조회 서비스

장애 분석 대시보드의 점이나 프로세서 이름을 클릭하면 그 Processor의 Provenance 이벤트를 보여 주는 기능입니다. 필요 없으면 건너뜁니다.

### 7.1 NiFi 조회용 계정 (exporter 계정과 **별도**)

| 유형 | 할 일 |
|---|---|
| ① 인증·권한 없음 | 계정이 필요 없습니다. `nifi.auth`는 exporter와 같은 `{ mode: none }`입니다. 대신 **7.2에서 `server.basic_auth`를 꼭 켭니다**(체크리스트 D7). 이 서비스 주소를 아는 사람은 누구나 Provenance를 조회할 수 있기 때문입니다 |
| ② Single User | 계정을 따로 만들 수 없으므로 exporter와 같은 관리자 계정을 씁니다 |
| ③·④ | 아래 권한만 가진 `nifi-provenance` 계정(또는 인증서)을 새로 만듭니다 |

③·④에서 조회용 계정에 줄 권한입니다.

| 정책 | 권한 |
|---|---|
| query provenance (`/provenance`) | view |
| 루트 Process Group → **view provenance** | view |
| 루트 Process Group → **view the component** | view |

### 7.2 설정과 실행

같은 프로그램 묶음에 들어 있으므로 추가 설치는 없습니다.

```bash
mkdir -p $PROVQ_CONF
cp $EXPORTER_CONF/config.yaml $PROVQ_CONF/config.yaml
vi $PROVQ_CONF/config.yaml
```

- `nifi.auth`의 계정·비밀번호 파일을 7.1의 조회용 계정으로 바꿉니다(예: `password_file: /appdata/nifi-monitoring/nifi-provenance-query/conf/password`, 경로는 `echo $PROVQ_CONF`로 확인한 실제 경로). ①은 그대로 `{ mode: none }`, ②는 exporter와 같은 관리자 계정입니다.
- 맨 아래 `provenance:` 절의 주석(`#`)을 풀어 줍니다.
- `nifi.cluster_name`은 exporter와 **같은 값**으로 둡니다.
- `server.basic_auth`를 쓰면 이 서비스의 모든 화면에 비밀번호가 걸립니다. 브라우저에서 바로 여는 서비스이므로, 내부망 제한만 할지 비밀번호를 걸지 정합니다. **①(인증·권한 없음)이면 비밀번호를 겁니다.**

```bash
chown -R $EXPORTER_USER: $PROVQ_CONF      # A(서비스별 계정)일 때만 바뀝니다
chmod 700 $PROVQ_CONF && chmod 600 $PROVQ_CONF/*

$EXPORTER_HOME/venv/bin/nifi-provenance-query --config $PROVQ_CONF/config.yaml --check-config
# A(서비스별 계정)는 앞에 sudo -u $EXPORTER_USER

sudo systemctl enable nifi-provenance-query      # 서비스 파일은 1.8에서 등록
sudo systemctl start nifi-provenance-query
curl -s localhost:9104/healthz; echo         # 응답이 오면 동작 중
```

### 7.3 대시보드 링크 주소 바꾸기

대시보드의 Provenance 링크 기본 주소는 `http://localhost:19104`(개발용)입니다. **사용자 PC의 브라우저에서 접속되는 주소**로 대시보드를 다시 만듭니다.

```bash
cd $REPO
NIFI_PROVENANCE_URL=http://<모니터링 서버>:9104 python3 deploy/grafana/build_dashboards.py
cp deploy/grafana/dashboards/*.json $GRAFANA_DASH/
sed -i 's/"timezone": "browser"/"timezone": "Asia\/Seoul"/' $GRAFANA_DASH/*.json      # 시간대 Asia/Seoul 고정 (6.2)
chmod -R a+rX $GRAFANA_DASH
```

Grafana가 몇십 초 안에 바뀐 파일을 다시 읽습니다. 사용자 PC에서 9104 포트로 접속할 수 있어야 합니다(1.8의 방화벽).

> 이 명령은 저장소의 `deploy/grafana/dashboards/*.json`을 바꿉니다. 저장소를 git으로 관리한다면 이 변경은 커밋하지 않습니다(`git checkout deploy/grafana/dashboards`로 되돌림).

---

## 8. (선택) 알림 중계 서비스

Slack·메일 말고 사내 당직·티켓·문자 시스템의 HTTP API로 알림을 보낼 때만 씁니다.

### 8.1 설정

```bash
mkdir -p $RELAY_CONF
cp $REPO/exporter/config/nifi-alert-relay.example.yaml $RELAY_CONF/config.yaml
sed -i "s#/etc/nifi-alert-relay/#$RELAY_CONF/#g" $RELAY_CONF/config.yaml   # 파일 속 경로(Docker 기준)를 내 경로로
vi $RELAY_CONF/config.yaml
```

- `targets:`에 보낼 곳을 적습니다. 예시의 `ops-api`(알림마다 1건, critical만), `ticket-webhook`(묶어서 1건)을 참고해 `url`, `headers`, `payload`를 사내 API 형식에 맞춥니다. 안 쓰는 대상은 지웁니다.
- 토큰은 파일에 직접 쓰지 않고 `${OPS_API_TOKEN}`처럼 환경변수로 둡니다(아래 환경 파일).
- `payload`의 `{startsAt}`, `{endsAt}`는 Alertmanager가 주는 **UTC 시각**(예: `2026-10-16T01:00:00Z`, 끝의 `Z`가 UTC 표시)입니다. 받는 시스템이 KST로 바꿔 보여 주는지 확인합니다(`01:00Z` = KST `10:00`).

```bash
openssl rand -hex 16 > $RELAY_CONF/password            # Alertmanager·Prometheus가 쓰는 비밀번호
echo 'OPS_API_TOKEN=<사내 API 토큰>' > $RELAY_CONF/env
chown -R $EXPORTER_USER: $RELAY_CONF      # A(서비스별 계정)일 때만 바뀝니다
chmod 700 $RELAY_CONF && chmod 600 $RELAY_CONF/*

env $(cat $RELAY_CONF/env) \
  $EXPORTER_HOME/venv/bin/nifi-alert-relay --config $RELAY_CONF/config.yaml --check-config
# A(서비스별 계정)는 앞에 sudo -u $EXPORTER_USER
```

### 8.2 서비스 시작

서비스 파일은 1.8에서 등록했습니다. 토큰은 `$RELAY_CONF/env`에서 읽습니다.

```bash
sudo systemctl enable nifi-alert-relay
sudo systemctl start nifi-alert-relay
```

### 8.3 Alertmanager·Prometheus 연결

```bash
# Alertmanager가 중계에 로그인할 비밀번호
cp $RELAY_CONF/password $AM_CONF/alert_relay_password
chown $AM_USER: $AM_CONF/alert_relay_password && chmod 600 $AM_CONF/alert_relay_password
# Prometheus가 중계 상태를 수집할 비밀번호
cp $RELAY_CONF/password $PROM_CONF/secrets/alert-relay-password
chown $PROM_USER: $PROM_CONF/secrets/alert-relay-password && chmod 600 $PROM_CONF/secrets/alert-relay-password
```

- `$AM_CONF/alertmanager.yml`의 `custom-relay` 수신처 `url`을 `http://localhost:9105/alerts`로 바꿉니다(5.2에서 지웠다면 저장소 파일에서 다시 가져옵니다).
- `$PROM_CONF/prometheus.yml`의 `nifi-alert-relay` job 대상을 `localhost:9105`로 바꿉니다(4.3에서 지웠다면 다시 추가).

```bash
amtool check-config $AM_CONF/alertmanager.yml && sudo systemctl reload alertmanager
promtool check config $PROM_CONF/prometheus.yml  && sudo systemctl reload prometheus
```

**확인** — 5.3의 `amtool alert add` 시험 알림을 다시 보내고, 대상 API에 도착했는지와 결과 카운터를 봅니다.

```bash
curl -s -u alertmanager:$(cat $RELAY_CONF/password) localhost:9105/metrics \
  | grep nifi_alert_relay_deliveries_total
```

`result="success"` 줄이 늘어나면 성공입니다.

---

## 9. 최종 점검

모든 항목이 맞으면 설치가 끝난 것입니다.

| # | 확인 | 방법 | 기대 결과 |
|---|---|---|---|
| 1 | 서비스 상태 | `systemctl is-active nifi-exporter prometheus alertmanager grafana-server` | 모두 `active` |
| 2 | 재부팅 후 자동 시작 | `systemctl is-enabled nifi-exporter prometheus alertmanager grafana-server` | 모두 `enabled` |
| 3 | collector 6개 성공 | Prometheus 화면(`:9090`)에서 `nifi_exporter_collector_success` 조회 | 모두 1 |
| 4 | exporter 하나만 | `count by (cluster) (up{job="nifi-exporter"})` 조회 | 1 |
| 5 | `cluster` 이름 일치 | `up{job="nifi-exporter"}`의 `cluster` 값 | exporter의 `nifi.cluster_name`과 같음 |
| 6 | heartbeat 정상 | `nifi_node_heartbeat_age_seconds` 조회 | 수 초~수십 초 (몇 시간이면 시간대 오류) |
| 7 | 규칙 평가 | `:9090/rules` 화면 | 오류 표시 없음 |
| 8 | 알림 도착 | 5.3 시험 알림 | Slack·메일 도착 |
| 9 | 대시보드 | Grafana **NiFi / 개요** | 노드 수와 값이 보임 |
| 10 | 시간대 | 모니터링 서버 `timedatectl`, NiFi `/flow/about`, 대시보드 오른쪽 위 시간 선택기 | 모두 Asia/Seoul(KST). 대시보드 시각이 지금 한국 시각과 같음 |

설치 직후 바로 대기(pending)나 발화(firing)하는 알림이 있을 수 있습니다(예: 디스크 80% 초과). 설정 오류가 아니라 **실제 상태**이므로 [docs/runbook.md](docs/runbook.md)를 보고 대응하거나 임계치를 조정합니다.

---

## 10. 문제 해결

먼저 로그를 봅니다: `journalctl -u <서비스 이름> -n 100 --no-pager`

| 증상 | 원인 | 해결 |
|---|---|---|
| exporter 로그에 `400 Invalid host header` | NiFi가 접속 주소를 모름 | NiFi `nifi.web.proxy.host`에 exporter가 쓰는 주소 추가 ([2.2](#22-유형별-준비)) |
| `401` | 계정·비밀번호 오류 | 비밀번호 파일 내용 확인, 2.2의 토큰 확인 |
| ② Single User에서 잘 되다가 갑자기 `401` | NiFi 관리자 비밀번호가 바뀜 | 새 비밀번호를 `$EXPORTER_CONF/password`에 넣고 `sudo systemctl restart nifi-exporter` |
| `https://` + `mode: none`으로 설정했더니 `401` | NiFi에 인증이 있음 (①이 아님) | 체크리스트 B0으로 유형을 다시 확인하고 `bearer`나 `mtls`로 설정 |
| `http://` 주소에서 `--check-config`가 `set nifi.auth.mode: none` 오류 | HTTP NiFi에는 인증이 없음 | `auth: { mode: none }`으로 바꿈 |
| `403` | 권한 부족 (③·④: 사용자는 있지만 정책이 없음) | 2.2의 정책 4개 확인. 어느 collector가 0인지 보면 빠진 정책을 알 수 있음 (`cluster`→`/controller`, `diagnostics`→`/system`, `flow`→`/flow`·루트 PG) |
| `CERTIFICATE_VERIFY_FAILED` | CA 파일이 틀림 | NiFi 관리자에게 올바른 CA(PEM) 받기. 임시로 `insecure_skip_verify: true` |
| Prometheus Targets에서 exporter가 `401` | `/metrics` 비밀번호 불일치 | 3.3과 4.3의 비밀번호 파일 내용이 같은지 확인, 둘 다 쓰거나 둘 다 지움 |
| Prometheus가 시작 안 됨 (`permission denied`) | 파일 소유자가 서비스 파일의 `User=`와 다름 | `ls -l $PROM_CONF $PROM_DATA`로 소유자 확인. 다르면 root가 `chown -R $PROM_USER: $PROM_CONF $PROM_DATA` |
| 서비스가 시작 안 됨, 로그에 `No such file` (`/appdata/...`) | 서비스 파일의 경로·계정이 변수 파일과 다름 (1.8 이후 변수 파일을 고침) | `grep -E '^(User\|ExecStart)=' $SYSTEMD_DIR/<서비스>.service`로 확인하고 root가 1.8의 서비스 파일 등록을 다시 실행 |
| Grafana 대시보드 폴더가 안 보임, 로그에 `permission denied` (`/appdata/...`) | grafana 계정이 `MON_HOME`의 파일을 읽지 못함 | `ls -ld /appdata /appdata/nifi-monitoring`(다른 계정 `x` 권한), `chmod -R a+rX $MON_HOME/grafana` |
| `sudo systemctl ...`에서 비밀번호를 물음 | 1.8의 위임에 없는 형태 | 서비스를 한 줄에 하나씩, 옵션 없이(`enable --now` 대신 `enable`과 `start`) 실행. `sudo -l`로 허용 목록 확인 |
| `NiFiNodeHeartbeatStale`이 계속 발화, heartbeat 경과가 몇 시간 | NiFi가 KST가 아님 (exporter는 Asia/Seoul 고정) | [2.3](#23-nifi-시간대-asiaseoul-확인)대로 NiFi를 Asia/Seoul로 바꾸거나, 그때까지 `nifi.timezone`을 NiFi 실제 시간대로 두고 `sudo systemctl restart nifi-exporter` |
| 대시보드 시각이 9시간 어긋남 | 대시보드 시간대가 `browser`로 남았고 PC가 UTC | 6.2의 `sed` 명령을 다시 실행 |
| 대시보드가 "No data" | 데이터소스 주소 또는 `cluster` 변수 | Grafana → Connections → Data sources → Prometheus → **Save & test**. `PROMETHEUS_URL` 확인 |
| 대시보드 폴더가 안 보임 | 등록 파일 위치 | `grep PROVISIONING_CFG_DIR $GRAFANA_ENV`가 `$GRAFANA_PROV`와 같은지, `$GRAFANA_DASH/*.json`이 있는지 확인. `journalctl -u grafana-server`에서 `provisioning` 오류 확인 |
| `NiFiExporterDuplicate` 발화 | exporter가 2개 수집됨 | 같은 클러스터의 exporter는 하나만 남김 |
| 알림이 하나도 안 옴 | 억제 중이거나 수신처 오류 | `:9093` 화면에서 알림 확인. 수집 장애 알림이 떠 있으면 다른 NiFi 알림은 일부러 억제됨 |
| `python3.11: command not found` | Python 미설치 | root에게 [1.8](#18-root-작업-모아-하기)의 Python 설치 요청 |
| `prometheus: command not found` | `$BIN_DIR`가 `PATH`에 없음 | 경로 변수를 불러오지 않음. 아래 줄 참고 |
| `/config.yaml: No such file`, `cp: missing destination` 등 경로가 이상함 | 새 터미널에서 경로 변수를 불러오지 않음 | `source /appdata/nifi-monitoring/nifi-mon.env` 후 다시 실행. `echo $EXPORTER_CONF`로 값 확인. 실행 계정은 `~/.bashrc`에 들어 있는지 확인(1.4) |

---

## 11. 업데이트와 제거

### 11.1 저장소 업데이트 반영

```bash
cd $REPO && git pull          # 또는 새 압축 파일로 교체

# exporter (Provenance 조회·알림 중계 포함)
$EXPORTER_HOME/venv/bin/pip install --upgrade $REPO/exporter
sudo systemctl restart nifi-exporter
sudo systemctl restart nifi-provenance-query      # 쓰는 경우
sudo systemctl restart nifi-alert-relay           # 쓰는 경우

# 규칙
cp $REPO/deploy/prometheus/rules/*.yml $PROM_CONF/rules/
promtool check rules $PROM_CONF/rules/*.yml && sudo systemctl reload prometheus

# 대시보드 (7.3을 했다면 NIFI_PROVENANCE_URL을 붙여 다시 생성한 뒤 복사)
cp $REPO/deploy/grafana/dashboards/*.json $GRAFANA_DASH/
sed -i 's/"timezone": "browser"/"timezone": "Asia\/Seoul"/' $GRAFANA_DASH/*.json      # 시간대 Asia/Seoul 고정 (6.2)
chmod -R a+rX $GRAFANA_DASH
```

`prometheus.yml`, `alertmanager.yml`은 직접 고친 파일이므로 덮어쓰지 말고, 저장소 쪽 변경 내용을 비교(`diff`)해 필요한 부분만 옮깁니다.

### 11.2 제거

root로 실행합니다. 변수 파일을 먼저 불러옵니다. `${변수:?}`는 변수가 비어 있으면 명령을 멈추게 해서, 엉뚱한 경로를 지우는 사고를 막습니다.

```bash
# [root]
source /appdata/nifi-monitoring/nifi-mon.env
for svc in nifi-exporter nifi-provenance-query nifi-alert-relay prometheus alertmanager grafana-server; do
  systemctl disable --now $svc 2>/dev/null
done
rm -f "${SYSTEMD_DIR:?}"/{nifi-exporter,nifi-provenance-query,nifi-alert-relay,prometheus,alertmanager}.service
rm -rf "${SYSTEMD_DIR:?}"/grafana-server.service.d       # 6.3에서 Grafana 계정을 바꿨을 때
systemctl daemon-reload
rm -f /etc/sudoers.d/nifi-monitoring
dnf remove -y grafana    # 또는 apt remove -y grafana
rm -rf "${MON_HOME:?}"   # 프로그램·설정·수집 데이터·변수 파일이 모두 지워집니다
```

실행용 리눅스 계정을 지웁니다(다른 용도로 쓰지 않는 계정일 때만).

```bash
# [root]
userdel -r monitor                                                   # B. 하나의 계정 (회사 운영 계정이면 지우지 않고 ~/.bashrc의 source 줄만 지웁니다)
userdel nifi-exporter; userdel prometheus; userdel alertmanager     # A. 서비스별 계정
```

1.8에서 연 방화벽 포트(3000, 9104)도 닫습니다. NiFi에 만든 `nifi-monitor`(와 `nifi-provenance`) 계정·정책은 NiFi UI에서 지웁니다.
