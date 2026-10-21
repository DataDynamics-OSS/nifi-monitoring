#!/usr/bin/env bash
# 폐쇄망(airgap) RHEL 9 x86_64 서버용 nifi-exporter 의존 wheel을 Python 버전별 디렉터리에 받습니다.
# 인터넷이 되는 PC에서 실행합니다(PC의 OS·Python 버전은 상관없고 pip만 있으면 됩니다).
#
#   ./build.sh               → py3.9/, py3.11/ 를 다시 만듭니다
#   ./build.sh 3.9           → py3.9/ 만
#   PYTHON=python3 ./build.sh   다운로드에 쓸 pip의 Python
#
# 대상 서버: CPython 3.9(RHEL 9 기본 python3) 또는 3.11, x86_64, manylinux2014(glibc 2.17) 이상.
# 의존 라이브러리는 대상 서버용 manylinux/순수 Python wheel만 받으므로 서버에 컴파일러가 필요 없습니다.
# 결과 디렉터리에는 설치용 requirements.txt 사본도 둡니다(README "설치 방법" 참고).
set -euo pipefail
cd "$(dirname "$0")"

PYTHON=${PYTHON:-python3}
VERSIONS=("$@")
[ ${#VERSIONS[@]} -gt 0 ] || VERSIONS=(3.9 3.11)

download() { # <python-version> <dest> <requirement>...
    local ver=$1 dest=$2
    shift 2
    "$PYTHON" -m pip download --quiet --disable-pip-version-check --dest "$dest" --only-binary=:all: \
        --python-version "$ver" --implementation cp --abi "cp${ver/./}" \
        --platform manylinux2014_x86_64 "$@"
}

for ver in "${VERSIONS[@]}"; do
    case "$ver" in 3.9|3.11) ;; *) echo "지원하지 않는 Python 버전입니다: $ver (3.9 또는 3.11)" >&2; exit 1 ;; esac
    dest=py$ver
    rm -rf "$dest"
    mkdir "$dest"
    cp requirements.txt "$dest/"

    # 1) 실행 의존성(requirements.txt = pyproject.toml의 dependencies)과 전이 의존성
    download "$ver" "$dest" -r requirements.txt
    if [ "$ver" = 3.9 ]; then
        # pip는 의존성 마커(python_version < "3.11")를 실행 중인 pip의 Python 기준으로 평가하므로
        # 3.11 미만에서만 필요한 exceptiongroup은 명시해서 받습니다.
        download "$ver" "$dest" "exceptiongroup>=1.0.2"
        # 2) `pip install .` 빌드 백엔드. 3.9 venv의 기본 setuptools 53은 PEP 621 pyproject.toml을 읽지 못합니다.
        download "$ver" "$dest" "setuptools>=68" wheel
    fi

    echo "$dest/:"
    ls -1 "$dest" | sed 's/^/  /'
    du -sh "$dest" | awk '{print "  합계 " $1}'
done
