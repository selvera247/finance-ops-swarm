#!/usr/bin/env bash
# 3) Managed Spanner Graph–shaped tables + point Cloud Run at FINANCE_OPS_GRAPH_BACKEND=spanner.
# Neo4j Aura remains Option A — see scripts/go_live_neo4j_aura.md
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${FINANCE_OPS_REGION:-us-central1}"
INSTANCE="${SPANNER_INSTANCE:-finance-ops}"
DATABASE="${SPANNER_DATABASE:-finance_ops}"
SERVICE="${CLOUD_RUN_SERVICE:-finance-ops}"
CONFIG="${SPANNER_CONFIG:-regional-${REGION}}"

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

echo "==> Enable Spanner API"
gcloud services enable spanner.googleapis.com --project="${PROJECT}"

echo "==> Ensure instance ${INSTANCE}"
if ! gcloud spanner instances describe "${INSTANCE}" --project="${PROJECT}" >/dev/null 2>&1; then
  gcloud spanner instances create "${INSTANCE}" \
    --config="${CONFIG}" \
    --description="Finance ops KG" \
    --nodes=1 \
    --project="${PROJECT}"
fi

echo "==> Ensure database ${DATABASE}"
gcloud spanner databases create "${DATABASE}" \
  --instance="${INSTANCE}" \
  --project="${PROJECT}" 2>/dev/null || true

echo "==> Apply DDL (ignore if tables already exist)"
gcloud spanner databases ddl update "${DATABASE}" \
  --instance="${INSTANCE}" \
  --project="${PROJECT}" \
  --ddl-file="${ROOT}/data_plane/graph/spanner_schema.sql" || true

echo "==> Sync knowledge graph into Spanner"
export FINANCE_OPS_GRAPH_BACKEND=spanner
export SPANNER_INSTANCE="${INSTANCE}"
export SPANNER_DATABASE="${DATABASE}"
export GOOGLE_CLOUD_PROJECT="${PROJECT}"
PYTHONPATH="${ROOT}" python3 "${ROOT}/scripts/sync_knowledge_graph.py" --backend spanner --export

echo "==> Point Cloud Run at Spanner graph"
gcloud run services update "${SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --update-env-vars="FINANCE_OPS_GRAPH_BACKEND=spanner,SPANNER_INSTANCE=${INSTANCE},SPANNER_DATABASE=${DATABASE},GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --quiet

URI="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT}" --format='value(status.url)')"
echo "==> Smoke"
curl -sf "${URI}/v1/status" | tee /tmp/spanner_status.json | head -c 800; echo
echo "Done. Runtime SA needs roles/spanner.databaseUser on ${INSTANCE}/${DATABASE}."
