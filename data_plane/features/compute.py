from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from data_plane.warehouse import db


def compute_customer_features() -> dict[str, Any]:
    db.init_schema()
    now = datetime.now(timezone.utc)
    con = db.connect()
    try:
        con.execute("DELETE FROM customer_features")
        rows = con.execute(
            """
            SELECT c.customer_id, c.credit_limit,
              COALESCE(i.open_count, 0), COALESCE(i.open_ar, 0),
              COALESCE(i.past_due, 0), COALESCE(p.unmatched, 0)
            FROM contracts c
            LEFT JOIN (
              SELECT customer_id,
                COUNT(*) FILTER (WHERE status IN ('open','past_due')) AS open_count,
                SUM(CASE WHEN status IN ('open','past_due') THEN amount ELSE 0 END) AS open_ar,
                SUM(CASE WHEN status = 'past_due' THEN amount ELSE 0 END) AS past_due
              FROM invoices GROUP BY customer_id
            ) i USING (customer_id)
            LEFT JOIN (
              SELECT customer_id,
                COUNT(*) FILTER (WHERE status IN ('unmatched','partial')) AS unmatched
              FROM payments GROUP BY customer_id
            ) p USING (customer_id)
            WHERE c.status = 'active'
            """
        ).fetchall()
        written = 0
        for customer_id, credit_limit, open_count, open_ar, past_due, unmatched in rows:
            credit_limit = float(credit_limit or 0)
            open_ar = float(open_ar or 0)
            utilization = (open_ar / credit_limit) if credit_limit else 0.0
            if past_due >= 8000 or utilization >= 0.8:
                risk = "high"
            elif past_due > 0 or unmatched > 0:
                risk = "medium"
            else:
                risk = "low"
            con.execute(
                "INSERT INTO customer_features VALUES (?,?,?,?,?,?,?,?,?)",
                [customer_id, int(open_count or 0), open_ar, float(past_due or 0),
                 int(unmatched or 0), credit_limit, round(utilization, 4), risk, now],
            )
            written += 1
        run_id = f"features-{uuid.uuid4().hex[:10]}"
        con.execute(
            "INSERT OR REPLACE INTO pipeline_runs VALUES (?,?,?,?,?,?)",
            [run_id, "features", "success", f"rows={written}", now, now],
        )
        return {"status": "success", "customers": written, "run_id": run_id}
    finally:
        con.close()
