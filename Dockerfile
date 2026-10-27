# L6 Cloud Run image: FastAPI HTTP API (default) or ADK api_server (same image).
# FINANCE_OPS_SERVE_MODE=http|adk — see deploy/entrypoint.sh
FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    FINANCE_OPS_DATA_MODE=warehouse \
    FINANCE_OPS_SERVE_MODE=http \
    PORT=8080

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-cloud.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-cloud.txt

COPY data ./data
COPY data_plane ./data_plane
COPY finance_ops ./finance_ops
COPY pipelines ./pipelines
COPY gui_connectors ./gui_connectors
COPY evals ./evals
COPY deploy ./deploy

RUN chmod +x /app/deploy/entrypoint.sh \
    && mkdir -p /app/.warehouse /app/.evidence /app/.downloads

EXPOSE 8080
CMD ["/app/deploy/entrypoint.sh"]
