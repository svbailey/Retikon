from pathlib import Path

import duckdb

from retikon_core.query_engine.warm_start import get_secure_connection


def _write_healthcheck(path: Path) -> None:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    safe_path = str(path).replace("'", "''")
    conn.execute(f"COPY t TO '{safe_path}' (FORMAT 'parquet')")
    conn.close()


def test_warm_start_local_healthcheck(tmp_path: Path) -> None:
    healthcheck = tmp_path / "healthcheck.parquet"
    _write_healthcheck(healthcheck)

    conn, auth = get_secure_connection(healthcheck_uri=str(healthcheck))
    try:
        assert auth.auth_path == "none"
    finally:
        conn.close()
