#!/usr/bin/env bash
# 1) Enable BigQuery API, create dataset/tables, load demo JSON, point Cloud Run at BQ.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${FINANCE_OPS_REGION:-us-central1}"
DATASET="${FINANCE_OPS_BQ_DATASET:-finance_ops}"
SERVICE="${CLOUD_RUN_SERVICE:-finance-ops}"

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

echo "==> Enable BigQuery API"
gcloud services enable bigquery.googleapis.com --project="${PROJECT}"

echo "==> Ensure dataset"
bq --location="${REGION}" mk -d --description "Finance ops demo" "${PROJECT}:${DATASET}" 2>/dev/null || true

echo "==> Apply table DDL"
DDL="$(mktemp)"
sed "s/\${PROJECT}/${PROJECT}/g; s/\${DATASET}/${DATASET}/g" \
  "${ROOT}/data_plane/warehouse/bq_schema.sql" >"${DDL}"
bq query --use_legacy_sql=false --project_id="${PROJECT}" <"${DDL}"

echo "==> Load demo JSON (replace)"
for table in invoices payments contracts; do
  bq load --autodetect --replace --source_format=NEWLINE_DELIMITED_JSON \
    "${PROJECT}:${DATASET}.${table}" \
    <(python3 - <<PY
import json
from pathlib import Path
rows = json.loads(Path("${ROOT}/data/${table}.json").read_text())
for r in rows:
    print(json.dumps(r))
PY
)
  echo "loaded ${table}"
done

echo "==> Point Cloud Run at BigQuery mode"
gcloud run services update "${SERVICE}" \
  --region="${REGION}" \
  --project="${PROJECT}" \
  --update-env-vars="FINANCE_OPS_DATA_MODE=bigquery,FINANCE_OPS_BQ_DATASET=${DATASET},GOOGLE_CLOUD_PROJECT=${PROJECT}" \
  --quiet

URI="$(gcloud run services describe "${SERVICE}" --region="${REGION}" --project="${PROJECT}" --format='value(status.url)')"
echo "==> Smoke"
curl -sf "${URI}/v1/status" | tee /tmp/bq_status.json | head -c 500; echo
echo "Done. Set Cloud Run runtime SA BigQuery Job User + Data Editor if status shows permission errors."
