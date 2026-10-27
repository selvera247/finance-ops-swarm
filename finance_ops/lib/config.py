from __future__ import annotations

import os

from data_plane.config import bigquery_dataset, data_mode, gcp_project  # noqa: F401


def use_bigquery() -> bool:
    return data_mode() == "bigquery"


def default_model() -> str:
    return os.getenv("FINANCE_OPS_MODEL", "gemini-3.1-flash-lite")
