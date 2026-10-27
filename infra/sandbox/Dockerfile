# C7-C — minimal guest image for sandboxed Python (no finance_ops, no creds).
# Build from repo root:
#   docker build -f infra/sandbox/Dockerfile -t finance-ops-sandbox:latest .
FROM python:3.12-slim-bookworm

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin sandbox \
    && mkdir -p /app \
    && chown sandbox:sandbox /app

COPY finance_ops/runtime/sandbox_worker.py /app/worker.py

WORKDIR /app
USER sandbox

# -I: isolated mode (ignore PYTHON* / user site)
ENTRYPOINT ["python", "-I", "/app/worker.py"]
