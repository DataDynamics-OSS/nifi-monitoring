# Airgap 설치 패키지 (offline wheels)

인터넷이 차단된(airgap) 환경에서 `nifi-exporter`를 설치하기 위한 pip wheel 모음입니다.

## 대상 환경

- OS: RHEL 9.6 (x86_64)
- Python: 3.11
- ABI/플랫폼: `cp311` / `manylinux2014_x86_64`

> wheel은 위 환경에 맞춰 교차 다운로드되었습니다. `pyyaml`만 C 확장 네이티브 wheel이고
> 나머지는 pure-python(`py3-none-any`)이라 아키텍처에 무관합니다.

## 포함 패키지

런타임 의존성(`prometheus-client`, `httpx`, `PyYAML`)과 그 전이 의존성 전체:

| 패키지 | 비고 |
|---|---|
| prometheus_client | 직접 의존 |
| httpx | 직접 의존 |
| pyyaml | 직접 의존 (C 확장, cp311 네이티브) |
| anyio | httpx 전이 |
| sniffio | anyio 전이 |
| certifi | httpx 전이 |
| httpcore | httpx 전이 |
| h11 | httpcore 전이 |
| idna | httpx 전이 |
| typing_extensions | anyio 전이 |

## 설치 방법

### 1. 패키지 전송

이 `packages/` 디렉터리(그리고 exporter 본체를 함께 설치하려면 프로젝트 루트 전체)를
USB·내부 아티팩트 저장소 등으로 airgap 서버에 복사합니다.

```bash
# 예: 프로젝트 루트를 통째로 복사
scp -r exporter/ root@<airgap-host>:/opt/
```

### 2. 가상환경 생성 (권장)

```bash
cd /opt/exporter
python3.11 -m venv .venv
source .venv/bin/activate
```

### 3. 오프라인 설치

의존성만 설치:

```bash
pip install --no-index --find-links packages/ -r packages/requirements.txt
```

exporter 본체까지 함께 설치:

```bash
pip install --no-index --find-links packages/ .
```

> 본체(`pip install .`) 설치 시 빌드 백엔드인 `setuptools`/`wheel`이 타깃에 이미 있어야 합니다.
> RHEL 9.6 기본 `python3.11` + `python3.11-pip`에는 포함되어 있습니다. 완전 격리가 필요하면
> `setuptools`·`wheel`·`pip` wheel도 이 디렉터리에 추가로 받아두세요.

### 4. 설치 확인

```bash
pip list | grep -E 'prometheus-client|httpx|PyYAML|nifi-exporter'
nifi-exporter --help
```

## 참고: wheel 재다운로드 방법

인터넷이 되는 환경에서 아래 명령으로 동일하게 재생성할 수 있습니다.

```bash
pip download -r packages/requirements.txt -d packages \
    --only-binary=:all: \
    --python-version 3.11 --implementation cp --abi cp311 \
    --platform manylinux2014_x86_64
```
