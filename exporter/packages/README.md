# Airgap 설치 패키지 (offline wheels)

인터넷이 차단된(airgap) 환경에서 `nifi-exporter`를 설치하기 위한 pip wheel 모음입니다.
대상 Python 버전별로 디렉터리가 나뉘어 있습니다.

| 디렉터리 | Python | ABI / 플랫폼 |
|---|---|---|
| `py3.11/` | 3.11 | `cp311` / `manylinux2014_x86_64` |
| `py3.9/` | 3.9 (RHEL 9.6 기본 `python3`) | `cp39` / `manylinux2014_x86_64` |

- OS: RHEL 9.6 (x86_64)
- 각 디렉터리에는 동일한 `requirements.txt`가 들어 있습니다(루트의 것과 같습니다).

> wheel은 위 환경에 맞춰 교차 다운로드되었습니다. `pyyaml`만 C 확장 네이티브 wheel이고
> 나머지는 pure-python(`py3-none-any`)이라 아키텍처에 무관합니다.

## 포함 패키지

런타임 의존성(`prometheus-client`, `httpx`, `PyYAML`)과 그 전이 의존성 전체:

| 패키지 | py3.11 | py3.9 | 비고 |
|---|---|---|---|
| prometheus_client | 0.26.0 | 0.26.0 | 직접 의존 |
| httpx | 0.28.1 | 0.28.1 | 직접 의존 |
| pyyaml | 6.0.3 (cp311) | 6.0.3 (cp39) | 직접 의존 (C 확장 네이티브) |
| anyio | 4.15.1 | 4.12.1 | httpx 전이 (4.13부터 3.9 미지원이라 버전이 다름) |
| sniffio | 1.3.1 | - | anyio 4.15 전이 |
| exceptiongroup | - | 1.3.1 | anyio 전이 (Python < 3.11 에서만 필요) |
| certifi | 2026.10.18 | 2026.10.18 | httpx 전이 |
| httpcore | 1.0.9 | 1.0.9 | httpx 전이 |
| h11 | 0.16.0 | 0.16.0 | httpcore 전이 |
| idna | 3.20 | 3.20 | httpx 전이 |
| typing_extensions | 4.16.0 | 4.16.0 | anyio 전이 |
| setuptools | - | 82.0.1 | 빌드 백엔드 (`pip install .` 용) |
| wheel | - | 0.48.0 | 빌드 백엔드 |
| packaging | - | 26.3 | setuptools·wheel 전이 |

## 설치 방법

아래에서 `PKG`를 대상 Python에 맞는 디렉터리로 두고 진행합니다.

```bash
PKG=packages/py3.11   # Python 3.11
PKG=packages/py3.9    # Python 3.9
```

### 1. 패키지 전송

이 `packages/` 디렉터리(그리고 exporter 본체를 함께 설치하려면 프로젝트 루트 전체)를
USB·내부 아티팩트 저장소 등으로 airgap 서버에 복사합니다. 필요한 버전 디렉터리만 복사해도 됩니다.

```bash
# 예: 프로젝트 루트를 통째로 복사
scp -r exporter/ root@<airgap-host>:/opt/
```

### 2. 가상환경 생성 (권장)

```bash
cd /opt/exporter
python3.11 -m venv .venv      # Python 3.9면 python3.9 -m venv .venv
source .venv/bin/activate
```

> RHEL 9.6 기본 `python3`(3.9)에는 시스템 pip가 없지만 `ensurepip`가 포함되어 있어
> `python3.9 -m venv`로 만든 가상환경 안에는 pip(21.3)가 자동으로 생깁니다.

### 3. 오프라인 설치

의존성만 설치:

```bash
pip install --no-index --find-links $PKG/ -r $PKG/requirements.txt
```

exporter 본체까지 함께 설치:

```bash
pip install --no-index --find-links $PKG/ .
```

> 본체(`pip install .`) 설치 시 pip가 격리된 빌드 환경에 `setuptools>=68`을 설치하므로, 해당 wheel이
> `--find-links` 디렉터리에 있어야 합니다. `py3.9/`에는 `setuptools`·`wheel`·`packaging`을 같이
> 넣어 두었습니다(3.9 venv의 기본 setuptools 53은 PEP 621 `pyproject.toml`을 읽지 못합니다).
> `py3.11/`은 RHEL 9.6의 `python3.11-setuptools`를 쓰거나 같은 방식으로 wheel을 추가해 주세요.

### 4. 설치 확인

```bash
pip list | grep -E 'prometheus-client|httpx|PyYAML|nifi-exporter'
nifi-exporter --help
```

## 참고: wheel 재다운로드 방법

인터넷이 되는 환경에서 `./build.sh`(인자 없이 두 버전 모두, `./build.sh 3.9`처럼 하나만)를 실행하면
`py3.9/`·`py3.11/`를 다시 만듭니다. 아래는 같은 일을 하는 pip 명령입니다.

```bash
# Python 3.11
pip download -r packages/requirements.txt -d packages/py3.11 \
    --only-binary=:all: \
    --python-version 3.11 --implementation cp --abi cp311 \
    --platform manylinux2014_x86_64

# Python 3.9
pip download -r packages/requirements.txt -d packages/py3.9 \
    --only-binary=:all: \
    --python-version 3.9 --implementation cp --abi cp39 \
    --platform manylinux2014_x86_64
# pip는 의존성 마커(python_version < "3.11")를 실행 중인 pip의 Python 기준으로 평가하므로,
# 3.11 이상 Python의 pip로 받을 때는 exceptiongroup을 따로 받아야 합니다.
pip download "exceptiongroup>=1.0.2" "setuptools>=68" wheel -d packages/py3.9 \
    --only-binary=:all: \
    --python-version 3.9 --implementation cp --abi cp39 \
    --platform manylinux2014_x86_64
```
