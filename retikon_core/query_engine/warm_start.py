from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

import duckdb

from retikon_core.errors import RecoverableError
from retikon_core.logging import get_logger
from retikon_core.query_engine.duckdb_auth import (
    DuckDBAuthContext,
    load_duckdb_auth_provider,
)

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


def get_secure_connection(
    *,
    healthcheck_uri: str | None,
) -> tuple[duckdb.DuckDBPyConnection, DuckDBAuthInfo]:
    allow_install = os.getenv("DUCKDB_ALLOW_INSTALL", "0") == "1"
    skip_healthcheck = os.getenv("DUCKDB_SKIP_HEALTHCHECK", "0") == "1"

    conn = duckdb.connect(database=":memory:")
    extensions_loaded = load_extensions(conn, ("httpfs", "vss"), allow_install)
    provider = load_duckdb_auth_provider()
    context = DuckDBAuthContext(
        uris=tuple(uri for uri in (healthcheck_uri,) if uri),
        allow_install=allow_install,
    )
    auth_path, fallback_used = provider.configure(conn, context)

    if healthcheck_uri and not skip_healthcheck:
        try:
            conn.execute(
                "SELECT 1 FROM read_parquet(?) LIMIT 1",
                [healthcheck_uri],
            )
        except Exception as exc:
            raise RecoverableError(
                "DuckDB healthcheck failed. "
                "Verify storage auth configuration and DuckDB secret setup."
            ) from exc

    logger.info(
        "DuckDB auth initialized",
        extra={
            "duckdb_auth_path": auth_path,
            "duckdb_extension_loaded": ",".join(extensions_loaded),
            "duckdb_fallback_used": fallback_used,
        },
    )

    return conn, DuckDBAuthInfo(
        auth_path=auth_path,
        extensions_loaded=extensions_loaded,
        fallback_used=fallback_used,
    )
