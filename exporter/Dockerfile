FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
USER 65534:65534
EXPOSE 9103 9104 9105
ENTRYPOINT ["nifi-exporter"]
CMD ["--config", "/etc/nifi-exporter/config.yaml"]
