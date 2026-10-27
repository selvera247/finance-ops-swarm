#!/usr/bin/env sh
# Same image, two surfaces:
#   FINANCE_OPS_SERVE_MODE=http (default) → FastAPI data plane API (live Cloud Run today)
#   FINANCE_OPS_SERVE_MODE=adk            → ADK api_server (Agent Engine–compatible agent surface)
set -eu
PORT="${PORT:-8080}"
export PYTHONPATH="${PYTHONPATH:-/app}"
MODE="$(printf '%s' "${FINANCE_OPS_SERVE_MODE:-http}" | tr '[:upper:]' '[:lower:]')"

case "${MODE}" in
  adk|agent|agent_engine|api_server)
    exec adk api_server --host 0.0.0.0 --port "${PORT}" --no-reload /app
    ;;
  http|fastapi|api|*)
    exec python -m uvicorn finance_ops.serving:app --host 0.0.0.0 --port "${PORT}"
    ;;
esac
