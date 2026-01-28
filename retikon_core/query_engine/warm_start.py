from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

import duckdb

from retikon_core.errors import RecoverableError
from retikon_core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DuckDBAuthInfo:
    auth_path: str
    extensions_loaded: tuple[str, ...]
    fallback_used: bool


def _load_extension(
    conn: duckdb.DuckDBPyConnection,
    name: str,
    allow_install: bool,
) -> None:
    try:
        conn.execute(f"LOAD {name}")
    except Exception as exc:
        if not allow_install:
            raise RecoverableError(f"DuckDB LOAD {name} failed: {exc}") from exc
        try:
            conn.execute(f"INSTALL {name}")
            conn.execute(f"LOAD {name}")
        except Exception as install_exc:
            raise RecoverableError(
                f"DuckDB INSTALL/LOAD {name} failed: {install_exc}"
            ) from install_exc


def load_extensions(
    conn: duckdb.DuckDBPyConnection,
    extensions: Iterable[str],
    allow_install: bool,
) -> tuple[str, ...]:
    loaded: list[str] = []
    for name in extensions:
        _load_extension(conn, name, allow_install)
        loaded.append(name)
    return tuple(loaded)


def _configure_gcs_secret(
    conn: duckdb.DuckDBPyConnection,
    use_fallback: bool,
    allow_install: bool,
) -> str:
    conn.execute("DROP SECRET IF EXISTS retikon_gcs")
    if use_fallback:
        _load_extension(conn, "gcs", allow_install)
        return "gcs_extension"
    conn.execute("CREATE SECRET retikon_gcs (TYPE GCS, PROVIDER credential_chain)")
    return "credential_chain"


def _is_gcs_uri(uri: str | None) -> bool:
    return bool(uri and uri.startswith("gs://"))


def get_secure_connection(
    *,
    healthcheck_uri: str | None,
) -> tuple[duckdb.DuckDBPyConnection, DuckDBAuthInfo]:
    allow_install = os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1"
    use_fallback = os.getenv("DUCKDB_GCS_FALLBACK", "0") == "1"
    skip_healthcheck = os.getenv("DUCKDB_SKIP_HEALTHCHECK", "0") == "1"

    conn = duckdb.connect(database=":memory:")
    extensions_loaded = load_extensions(conn, ("httpfs", "vss"), allow_install)
    auth_path = "none"
    if _is_gcs_uri(healthcheck_uri):
        auth_path = _configure_gcs_secret(conn, use_fallback, allow_install)

    if healthcheck_uri and not skip_healthcheck:
        try:
            conn.execute(
                "SELECT 1 FROM read_parquet(?) LIMIT 1",
                [healthcheck_uri],
            )
        except Exception as exc:
            raise RecoverableError(
                "DuckDB GCS healthcheck failed. "
                "Verify ADC/Workload Identity and DuckDB secret configuration."
            ) from exc

    logger.info(
        "DuckDB GCS auth initialized",
        extra={
            "duckdb_auth_path": auth_path,
            "duckdb_extension_loaded": ",".join(extensions_loaded),
            "duckdb_fallback_used": use_fallback,
        },
    )

    return conn, DuckDBAuthInfo(
        auth_path=auth_path,
        extensions_loaded=extensions_loaded,
        fallback_used=use_fallback,
    )
