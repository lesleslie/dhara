"""Pin dhara/storage/pg_schema.sql ↔ dhara/storage/postgres.py:_PG_SCHEMA.

Both files declare the dhara_objects table layout. They must stay aligned —
operators run the SQL file to bootstrap Postgres, then expect the Python
storage adapter to read/write the columns it creates.
"""

from __future__ import annotations

from pathlib import Path

_PG_SCHEMA_PATH = (
    Path(__file__).resolve().parents[2] / "dhara" / "storage" / "pg_schema.sql"
)
_PG_SCHEMA_CONSTANT = (
    Path(__file__).resolve().parents[2] / "dhara" / "storage" / "postgres.py"
)


def test_pg_schema_columns_match_python_constant() -> None:
    """Both declarations must include the same set of columns for dhara_objects.

    The SQL bootstrap file is what an operator runs against Postgres; the
    Python constant is what the runtime storage adapter creates on top. If
    either drops a column the other expects, the runtime blows up with a
    ``column ... does not exist`` error.
    """
    sql_text = _PG_SCHEMA_PATH.read_text(encoding="utf-8")
    py_text = _PG_SCHEMA_CONSTANT.read_text(encoding="utf-8")

    sql_has_oid = "oid BIGINT PRIMARY KEY" in sql_text
    sql_has_data = "data BYTEA" in sql_text
    sql_has_refs = "refs BYTEA" in sql_text

    py_has_oid = "oid BIGINT PRIMARY KEY" in py_text
    py_has_data = "data BYTEA" in py_text
    py_has_refs = "refs BYTEA" in py_text

    sql_cols = {
        name
        for name, present in (
            ("oid", sql_has_oid),
            ("data", sql_has_data),
            ("refs", sql_has_refs),
        )
        if present
    }
    py_cols = {
        name
        for name, present in (
            ("oid", py_has_oid),
            ("data", py_has_data),
            ("refs", py_has_refs),
        )
        if present
    }

    assert sql_cols == py_cols, (
        "dhara_objects columns diverge between pg_schema.sql and postgres.py:_PG_SCHEMA; "
        f"update both files together. sql_cols={sorted(sql_cols)} py_cols={sorted(py_cols)}"
    )
