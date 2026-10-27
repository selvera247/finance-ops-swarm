# L4 — Vertex embeddings + Vector Search

## What shipped

| Layer | Behavior |
| --- | --- |
| Local default | Hash embeddings + Matching Engine **simulator** (`.warehouse/vectors/`) |
| Vertex embeddings | `FINANCE_OPS_USE_VERTEX_VECTORS=true` + ADC + `google-cloud-aiplatform` |
| Live Vector Search | Also set `FINANCE_OPS_VECTOR_INDEX_ENDPOINT` (+ deployed index id) |

`search_policies` uses the same tool contract either way.

## Env

```env
FINANCE_OPS_USE_VERTEX_VECTORS=false
# true + GOOGLE_CLOUD_PROJECT for Vertex text-embedding-004
FINANCE_OPS_VERTEX_LOCATION=us-central1
FINANCE_OPS_EMBEDDING_MODEL=text-embedding-004
FINANCE_OPS_VECTOR_INDEX_ENDPOINT=
FINANCE_OPS_VECTOR_DEPLOYED_INDEX_ID=finance_ops_policies
```

## Commands

```bash
pip install -r requirements-cloud.txt
PYTHONPATH=. python -c "from data_plane.vectors.embed import build_policy_index; print(build_policy_index())"
# ADK: search policies for collections escalation and cite evidence_id
```

Terraform creates an embeddings GCS bucket (`infra/terraform`). Create/deploy the Matching Engine index in console or gcloud, then set the endpoint env on Cloud Run.
