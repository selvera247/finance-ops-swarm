#!/usr/bin/env bash
# 4) Deploy ADK Agent Engine from the same repo image contents (finance_ops + extras).
# Cloud Run HTTP API remains the default live surface (FINANCE_OPS_SERVE_MODE=http).
# Same Dockerfile can also run ADK api_server via FINANCE_OPS_SERVE_MODE=adk.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${FINANCE_OPS_REGION:-us-central1}"
DISPLAY_NAME="${AGENT_ENGINE_DISPLAY_NAME:-finance-ops}"
SERVICE="${CLOUD_RUN_SERVICE:-finance-ops}"
UPDATE_CR_MODE="${UPDATE_CLOUD_RUN_ADK_MODE:-0}"

if [[ -n "${GCP_SA_KEY_JSON:-}" ]]; then
  if [[ -f "${GCP_SA_KEY_JSON}" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="${GCP_SA_KEY_JSON}"
  else
    KEY_FILE="$(mktemp)"; printf '%s' "${GCP_SA_KEY_JSON}" >"${KEY_FILE}"
    export GOOGLE_APPLICATION_CREDENTIALS="${KEY_FILE}"
  fi
  gcloud auth activate-service-account --key-file="${GOOGLE_APPLICATION_CREDENTIALS}" --quiet
fi
gcloud config set project "${PROJECT}" --quiet

echo "==> Enable Vertex AI (Agent Engine)"
gcloud services enable aiplatform.googleapis.com --project="${PROJECT}"

cd "${ROOT}"
# Prefer venv adk if present
ADK_BIN="adk"
if [[ -x "${ROOT}/.venv/bin/adk" ]]; then
  ADK_BIN="${ROOT}/.venv/bin/adk"
fi

echo "==> adk deploy agent_engine (finance_ops + data plane packages)"
EXTRA=(
  --extra_packages="${ROOT}/data_plane"
  --extra_packages="${ROOT}/pipelines"
  --extra_packages="${ROOT}/gui_connectors"
  --extra_packages="${ROOT}/data"
)
CONFIG="${ROOT}/finance_ops/.agent_engine_config.json"
ARGS=(
  deploy agent_engine
  --project="${PROJECT}"
  --region="${REGION}"
  --display_name="${DISPLAY_NAME}"
  --description="Finance ops multi-agent (same codebase as Cloud Run image)"
  --agent_engine_config_file="${CONFIG}"
  "${EXTRA[@]}"
)
if [[ -n "${AGENT_ENGINE_ID:-}" ]]; then
  ARGS+=(--agent_engine_id="${AGENT_ENGINE_ID}")
fi
ARGS+=("${ROOT}/finance_ops")

set +e
"${ADK_BIN}" "${ARGS[@]}"
RC=$?
set -e

OUT_DIR="${ROOT}/.warehouse"
mkdir -p "${OUT_DIR}"
echo "{\"project\":\"${PROJECT}\",\"region\":\"${REGION}\",\"display_name\":\"${DISPLAY_NAME}\",\"exit_code\":${RC}}" \
  >"${OUT_DIR}/agent_engine_deploy.json"

if [[ "${UPDATE_CR_MODE}" == "1" ]]; then
  echo "==> Flip Cloud Run same image to ADK api_server mode"
  gcloud run services update "${SERVICE}" \
    --region="${REGION}" \
    --project="${PROJECT}" \
    --update-env-vars="FINANCE_OPS_SERVE_MODE=adk,GOOGLE_CLOUD_PROJECT=${PROJECT}" \
    --quiet
  URI="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT}" --format='value(status.url)')"
  echo "Cloud Run ADK mode: ${URI} (list agents via ADK api_server routes)"
fi

if [[ ${RC} -ne 0 ]]; then
  echo "Agent Engine deploy exited ${RC}. Re-run with ADC/SA + Vertex permissions." >&2
  exit "${RC}"
fi
echo "Done. HTTP API remains default on Cloud Run; Agent Engine is the managed ADK surface."
echo "Same-image ADK on Cloud Run: set FINANCE_OPS_SERVE_MODE=adk (or UPDATE_CLOUD_RUN_ADK_MODE=1)."
