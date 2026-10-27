#!/usr/bin/env bash
# Run parking-lot go-live steps 1→4 (BigQuery, Vector Search, Spanner, Agent Engine).
# Requires: GOOGLE_CLOUD_PROJECT + ADC or GCP_SA_KEY_JSON
#
# Optional skips:
#   SKIP_BQ=1 SKIP_VECTOR=1 SKIP_SPANNER=1 SKIP_AGENT_ENGINE=1
#   SKIP_VECTOR=1 recommended first run (Matching Engine create is 30–90+ min)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
export GOOGLE_CLOUD_PROJECT="${PROJECT}"
export FINANCE_OPS_REGION="${FINANCE_OPS_REGION:-us-central1}"

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

run_step() {
  local name="$1" skip="$2" cmd="$3"
  if [[ "${skip}" == "1" ]]; then
    echo "==> SKIP ${name}"
    return 0
  fi
  echo "==> RUN ${name}"
  bash -lc "${cmd}"
}

run_step "1 BigQuery API + demo tables" "${SKIP_BQ:-0}" \
  "bash '${ROOT}/scripts/go_live_bigquery.sh'"

run_step "2 Vertex Matching Engine index" "${SKIP_VECTOR:-1}" \
  "PYTHONPATH='${ROOT}' python3 '${ROOT}/scripts/go_live_vector_search.py'"

run_step "3 Spanner Graph tables" "${SKIP_SPANNER:-0}" \
  "bash '${ROOT}/scripts/go_live_spanner.sh'"

run_step "4 ADK Agent Engine" "${SKIP_AGENT_ENGINE:-0}" \
  "bash '${ROOT}/scripts/go_live_agent_engine.sh'"

echo
echo "Parking lot orchestrator finished for project=${PROJECT}"
echo "Neo4j Aura (alt to Spanner): scripts/go_live_neo4j_aura.md"
echo "Default Vector Search skip=1; re-run with SKIP_VECTOR=0 when ready for long ME create."
