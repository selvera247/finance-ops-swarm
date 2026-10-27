from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb

from data_plane.config import DUCKDB_PATH, ensure_dirs

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(read_only: bool = False) -> duckdb.DuckDBPyConnection:
    ensure_dirs()
    return duckdb.connect(str(DUCKDB_PATH), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection | None = None) -> None:
    own = con is None
    con = con or connect()
    try:
        con.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        if own:
            con.close()


def query_dicts(sql: str, params: list[Any] | None = None) -> list[dict[str, Any]]:
    con = connect(read_only=True)
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    finally:
        con.close()


def execute(sql: str, params: list[Any] | None = None) -> None:
    con = connect()
    try:
        con.execute(sql, params or [])
    finally:
        con.close()
