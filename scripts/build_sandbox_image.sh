#!/usr/bin/env bash
# Build the C7-C sandbox worker image.
# Usage: bash scripts/build_sandbox_image.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
IMAGE="${FINANCE_OPS_SANDBOX_IMAGE:-finance-ops-sandbox:latest}"
docker build -f "${ROOT}/infra/sandbox/Dockerfile" -t "${IMAGE}" "${ROOT}"
echo "Built ${IMAGE}"
echo "Enable with: export FINANCE_OPS_SANDBOX_ISOLATION=container"
echo "Optional gVisor: export FINANCE_OPS_SANDBOX_RUNTIME=runsc"
