#!/usr/bin/env bash
# Take L4/L5/L6 from implemented → live in a GCP project.
#
# Required:
#   GOOGLE_CLOUD_PROJECT
#   Auth: gcloud ADC  OR  GCP_SA_KEY_JSON=/path/to/key.json  OR  GOOGLE_APPLICATION_CREDENTIALS
#
# Optional:
#   FINANCE_OPS_REGION (default us-central1)
#   TAG (default latest)
#   SKIP_VECTOR_INDEX=1  — skip Matching Engine index create (still enables Vertex embeds)
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${FINANCE_OPS_REGION:-us-central1}"
TAG="${TAG:-latest}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/finance-agents"
IMAGE="${REPO}/finance-ops:${TAG}"

echo "==> Auth"
if [[ -n "${GCP_SA_KEY_JSON:-}" ]]; then
  if [[ -f "${GCP_SA_KEY_JSON}" ]]; then
    export GOOGLE_APPLICATION_CREDENTIALS="${GCP_SA_KEY_JSON}"
  else
    # Inline JSON string
    KEY_FILE="$(mktemp)"
    printf '%s' "${GCP_SA_KEY_JSON}" >"${KEY_FILE}"
    export GOOGLE_APPLICATION_CREDENTIALS="${KEY_FILE}"
  fi
  gcloud auth activate-service-account --key-file="${GOOGLE_APPLICATION_CREDENTIALS}" --quiet
fi
gcloud config set project "${PROJECT}" --quiet

echo "==> Enable APIs"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  cloudbuild.googleapis.com \
  aiplatform.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  iam.googleapis.com \
  pubsub.googleapis.com \
  --project="${PROJECT}"

echo "==> Terraform (registry, SA, BQ, bucket, then Cloud Run after image)"
cd "${ROOT}/infra/terraform"
terraform init -input=false
terraform apply -auto-approve \
  -var="project_id=${PROJECT}" \
  -var="region=${REGION}" \
  -var="image=" \
  -var='invoker_members=[]'

AR="$(terraform output -raw artifact_registry)"
BUCKET_URL="$(terraform output -raw embeddings_bucket)"
BUCKET="${BUCKET_URL#gs://}"
SA_EMAIL="$(terraform output -raw service_account_email)"
echo "Artifact Registry: ${AR}"
echo "Embeddings bucket: ${BUCKET}"
echo "Runtime SA: ${SA_EMAIL}"

echo "==> Build & push image (Cloud Build — no local daemon required)"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
# Prefer Cloud Build; fall back to local docker
if gcloud builds submit "${ROOT}" --tag "${IMAGE}" --project="${PROJECT}" --quiet; then
  echo "Image pushed via Cloud Build: ${IMAGE}"
else
  echo "Cloud Build failed — trying local docker"
  docker build -t "${IMAGE}" "${ROOT}"
  docker push "${IMAGE}"
fi

echo "==> Terraform apply Cloud Run (L4/L5/L6 env live)"
terraform apply -auto-approve \
  -var="project_id=${PROJECT}" \
  -var="region=${REGION}" \
  -var="image=${IMAGE}" \
  -var="use_vertex_vectors=true" \
  -var="graph_backend=sqlite" \
  -var='invoker_members=["allUsers"]'

URI="$(terraform output -raw cloud_run_uri)"
echo "Cloud Run URI: ${URI}"

echo "==> L4: build local embeddings catalog and upload to GCS"
cd "${ROOT}"
PYTHONPATH=. python - <<'PY'
from data_plane.vectors.embed import build_policy_index
from pipelines.batch.ingest import ingest_batch
ingest_batch(run_id="gcp-go-live")
print(build_policy_index())
PY
gsutil -m cp -r "${ROOT}/.warehouse/vectors/" "gs://${BUCKET}/vectors/" || \
  gcloud storage cp -r "${ROOT}/.warehouse/vectors/**" "gs://${BUCKET}/vectors/"

if [[ "${SKIP_VECTOR_INDEX:-0}" != "1" ]]; then
  echo "==> L4: Matching Engine index create is async/long; writing endpoint stub env instructions"
  cat >"${ROOT}/.warehouse/gcp_vector_index_next.txt" <<EOF
Embeddings uploaded to gs://${BUCKET}/vectors/
To attach a live Vector Search endpoint later:
  1. Console → Vertex AI → Vector Search → Create Index from GCS embeddings
  2. Deploy index to an endpoint
  3. gcloud run services update finance-ops --region=${REGION} \\
       --update-env-vars=FINANCE_OPS_VECTOR_INDEX_ENDPOINT=ENDPOINT_RESOURCE_NAME,FINANCE_OPS_VECTOR_DEPLOYED_INDEX_ID=finance_ops_policies
Until then Cloud Run uses Vertex embeddings (when ADC works) + in-container ME simulator.
EOF
  cat "${ROOT}/.warehouse/gcp_vector_index_next.txt"
fi

echo "==> Bootstrap + smoke against Cloud Run"
curl -sf -X POST "${URI}/v1/bootstrap" | tee /tmp/finance_ops_bootstrap.json
curl -sf "${URI}/health" | tee /tmp/finance_ops_health.json
curl -sf -X POST "${URI}/v1/aging" -H 'Content-Type: application/json' \
  -d '{"customer_id":"CUST-ACME"}' | tee /tmp/finance_ops_aging.json
curl -sf -X POST "${URI}/v1/search_policies" -H 'Content-Type: application/json' \
  -d '{"query":"collections escalation"}' | tee /tmp/finance_ops_search.json
curl -sf "${URI}/v1/status" | tee /tmp/finance_ops_status.json

echo
echo "=== LIVE ==="
echo "Health: ${URI}/health"
echo "Status: ${URI}/v1/status"
echo "Project: ${PROJECT}  Region: ${REGION}"
echo "Done."
