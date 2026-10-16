PY ?= .venv/bin/python
PYTHON ?= python3

.PHONY: venv install test lint run docker lib dist dist-test

venv:
	uv venv --python 3.11 .venv

install:
	uv pip install --python $(PY) -e ".[dev]"

test:
	$(PY) -m pytest -q

lint:
	$(PY) -m ruff check src tests

run:
	$(PY) -m nifi_exporter --config config/nifi-exporter.example.yaml

docker:
	docker build -t nifi-exporter:0.1.0 .

# 이 디렉토리에서 bin/ 스크립트를 바로 쓰도록 의존 라이브러리를 lib/에 받습니다
lib:
	$(PYTHON) -m pip install --quiet --target lib --upgrade \
	  $$($(PYTHON) -c 'import tomllib; print(*tomllib.load(open("pyproject.toml", "rb"))["project"]["dependencies"])')
	rm -rf lib/bin

# 설치 없이 bin/ 스크립트로 실행하는 묶음입니다. PYTHON=python3.11로 빌드 Python을 고릅니다
dist:
	./build-dist.sh

dist-test: dist
	./smoke-test.sh
