# Terraform — GCP Data → AI (L3–L6)

Provisions:

- BigQuery dataset `finance_ops`
- Pub/Sub topic/subscription
- Artifact Registry `finance-agents`
- Runtime service account + BQ / AI Platform IAM
- GCS bucket for vector embeddings export (L4)
- Cloud Run v2 service when `image` is set (L6)

## Usage

```bash
cd infra/terraform
terraform init
terraform plan -var="project_id=YOUR_GCP_PROJECT"

# After docker push:
terraform apply \
  -var="project_id=YOUR_GCP_PROJECT" \
  -var="image=us-central1-docker.pkg.dev/YOUR_GCP_PROJECT/finance-agents/finance-ops:latest" \
  -var='invoker_members=["allUsers"]'
```

Or: `bash scripts/deploy_cloud_run.sh` from repo root.

Local DuckDB remains default without GCP (`FINANCE_OPS_DATA_MODE=warehouse`).
