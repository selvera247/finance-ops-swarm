from __future__ import annotations

"""BigQuery adapter (L3). Falls back to DuckDB when client/project unavailable."""

from typing import Any

from data_plane.config import bigquery_dataset, gcp_project


def bq_available() -> bool:
    """True when google-cloud-bigquery imports and GOOGLE_CLOUD_PROJECT is set."""
    if not gcp_project():
        return False
    try:
        from google.cloud import bigquery  # noqa: F401
    except ImportError:
        return False
    return True


def bq_ping() -> dict[str, Any]:
    """Lightweight connectivity probe for status tools / CI without credentials."""
    project = gcp_project()
    dataset = bigquery_dataset()
    if not project:
        return {
            "ok": False,
            "mode": "fallback_duckdb",
            "reason": "GOOGLE_CLOUD_PROJECT unset",
            "dataset": dataset,
        }
    try:
        from google.cloud import bigquery
    except ImportError:
        return {
            "ok": False,
            "mode": "fallback_duckdb",
            "reason": "google-cloud-bigquery not installed",
            "project": project,
            "dataset": dataset,
        }
    try:
        client = bigquery.Client(project=project)
        # Cheap metadata call — fails fast without valid ADC
        list(client.list_datasets(max_results=1))
        return {
            "ok": True,
            "mode": "bigquery",
            "project": project,
            "dataset": dataset,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "mode": "fallback_duckdb",
            "reason": str(exc),
            "project": project,
            "dataset": dataset,
        }


def _client():
    try:
        from google.cloud import bigquery
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("google-cloud-bigquery not installed") from exc
    project = gcp_project()
    if not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required for BigQuery mode")
    return bigquery.Client(project=project), project


def bq_list_invoices(
    *, customer_id: str | None = None, open_only: bool = False
) -> list[dict[str, Any]]:
    try:
        client, project = _client()
        dataset = bigquery_dataset()
        from google.cloud import bigquery

        sql = f"SELECT * FROM `{project}.{dataset}.invoices` WHERE 1=1"
        params = []
        if customer_id:
            sql += " AND customer_id = @customer_id"
            params.append(bigquery.ScalarQueryParameter("customer_id", "STRING", customer_id))
        if open_only:
            sql += " AND status IN ('open', 'past_due')"
        job_config = bigquery.QueryJobConfig(query_parameters=params) if params else None
        return [dict(row) for row in client.query(sql, job_config=job_config)]
    except Exception:
        from data_plane.warehouse import db

        sql = "SELECT * FROM invoices WHERE 1=1"
        params_list: list[Any] = []
        if customer_id:
            sql += " AND customer_id = ?"
            params_list.append(customer_id)
        if open_only:
            sql += " AND status IN ('open', 'past_due')"
        return db.query_dicts(sql, params_list)


def bq_list_payments(
    *, customer_id: str | None = None, unmatched_only: bool = False
) -> list[dict[str, Any]]:
    try:
        client, project = _client()
        dataset = bigquery_dataset()
        from google.cloud import bigquery

        sql = f"SELECT * FROM `{project}.{dataset}.payments` WHERE 1=1"
        job_config = None
        if customer_id:
            sql += " AND customer_id = @customer_id"
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("customer_id", "STRING", customer_id)
                ]
            )
        if unmatched_only:
            sql += " AND status IN ('unmatched', 'partial')"
        return [dict(row) for row in client.query(sql, job_config=job_config)]
    except Exception:
        from data_plane.warehouse import db

        sql = "SELECT * FROM payments WHERE 1=1"
        params_list: list[Any] = []
        if customer_id:
            sql += " AND customer_id = ?"
            params_list.append(customer_id)
        if unmatched_only:
            sql += " AND status IN ('unmatched', 'partial')"
        return db.query_dicts(sql, params_list)


def bq_list_contracts(
    *, customer_id: str | None = None, active_only: bool = True
) -> list[dict[str, Any]]:
    try:
        client, project = _client()
        dataset = bigquery_dataset()
        from google.cloud import bigquery

        sql = f"SELECT * FROM `{project}.{dataset}.contracts` WHERE 1=1"
        job_config = None
        if customer_id:
            sql += " AND customer_id = @customer_id"
            job_config = bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ScalarQueryParameter("customer_id", "STRING", customer_id)
                ]
            )
        if active_only:
            sql += " AND status = 'active'"
        return [dict(row) for row in client.query(sql, job_config=job_config)]
    except Exception:
        from data_plane.warehouse import db

        sql = "SELECT * FROM contracts WHERE 1=1"
        params_list: list[Any] = []
        if customer_id:
            sql += " AND customer_id = ?"
            params_list.append(customer_id)
        if active_only:
            sql += " AND status = 'active'"
        return db.query_dicts(sql, params_list)


def bq_get_invoice(invoice_id: str) -> dict[str, Any] | None:
    rows = bq_list_invoices()
    for row in rows:
        if str(row.get("invoice_id", "")).upper() == invoice_id.upper():
            return row
    return None


def bq_get_payment(payment_id: str) -> dict[str, Any] | None:
    rows = bq_list_payments()
    for row in rows:
        if str(row.get("payment_id", "")).upper() == payment_id.upper():
            return row
    return None


def bq_apply_payment_match(payment_id: str, invoice_id: str) -> dict[str, Any]:
    """Set payment status=matched in BigQuery (and matched_invoice_id when column exists)."""
    try:
        client, project = _client()
        dataset = bigquery_dataset()
        from google.cloud import bigquery

        table = f"`{project}.{dataset}.payments`"
        # Prefer full update; fall back if matched_invoice_id column missing
        sql_full = f"""
        UPDATE {table}
        SET status = @status, matched_invoice_id = @invoice_id
        WHERE payment_id = @payment_id
        """
        sql_status = f"""
        UPDATE {table}
        SET status = @status
        WHERE payment_id = @payment_id
        """
        params = [
            bigquery.ScalarQueryParameter("status", "STRING", "matched"),
            bigquery.ScalarQueryParameter("invoice_id", "STRING", invoice_id),
            bigquery.ScalarQueryParameter("payment_id", "STRING", payment_id),
        ]
        try:
            job = client.query(
                sql_full, job_config=bigquery.QueryJobConfig(query_parameters=params)
            )
            job.result()
            return {"ok": True, "rows_affected": job.num_dml_affected_rows, "mode": "full"}
        except Exception:
            params_status = [
                bigquery.ScalarQueryParameter("status", "STRING", "matched"),
                bigquery.ScalarQueryParameter("payment_id", "STRING", payment_id),
            ]
            job = client.query(
                sql_status,
                job_config=bigquery.QueryJobConfig(query_parameters=params_status),
            )
            job.result()
            return {
                "ok": True,
                "rows_affected": job.num_dml_affected_rows,
                "mode": "status_only",
                "note": "matched_invoice_id column absent; status updated only",
            }
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
