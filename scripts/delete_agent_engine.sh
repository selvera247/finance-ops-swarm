#!/usr/bin/env bash
# Delete idle Vertex Agent Engine / reasoning engine (hygiene).
# Usage:
#   bash scripts/delete_agent_engine.sh
#   ENGINE_ID=4038238202861977600 bash scripts/delete_agent_engine.sh
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-gen-lang-client-0611250410}"
REGION="${REGION:-us-central1}"
ENGINE_ID="${ENGINE_ID:-4038238202861977600}"
BASE="https://${REGION}-aiplatform.googleapis.com/v1/projects/${PROJECT}/locations/${REGION}/reasoningEngines"

TOKEN="$(gcloud auth print-access-token)"
echo "==> Listing reasoning engines in ${PROJECT}/${REGION}"
curl -sS -H "Authorization: Bearer ${TOKEN}" "${BASE}" | head -c 4000
echo
echo
echo "==> DELETE ${ENGINE_ID}"
curl -sS -X DELETE -H "Authorization: Bearer ${TOKEN}" "${BASE}/${ENGINE_ID}"
echo
echo "Done. Cloud Run finance-ops is unchanged."
