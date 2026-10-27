#!/usr/bin/env bash
# L6: build + push image, terraform apply Cloud Run
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${FINANCE_OPS_REGION:-us-central1}"
REPO="${REGION}-docker.pkg.dev/${PROJECT}/finance-agents"
IMAGE="${REPO}/finance-ops:${TAG:-latest}"

echo "Building ${IMAGE}"
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker build -t "${IMAGE}" "${ROOT}"
docker push "${IMAGE}"

cd "${ROOT}/infra/terraform"
terraform init -input=false
terraform apply -auto-approve \
  -var="project_id=${PROJECT}" \
  -var="region=${REGION}" \
  -var="image=${IMAGE}" \
  -var='invoker_members=["allUsers"]'

echo "URI: $(terraform output -raw cloud_run_uri 2>/dev/null || true)"
