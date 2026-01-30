from __future__ import annotations

import importlib
import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import duckdb

from retikon_core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DuckDBAuthContext:
    uris: tuple[str, ...]
    allow_install: bool


class DuckDBAuthProvider(Protocol):
    def configure(
        self,
        conn: duckdb.DuckDBPyConnection,
        context: DuckDBAuthContext,
    ) -> tuple[str, bool]:
        """Return (auth_path, fallback_used)."""


class NoopDuckDBAuthProvider:
    def configure(
        self,
        conn: duckdb.DuckDBPyConnection,
        context: DuckDBAuthContext,
    ) -> tuple[str, bool]:
        return "none", False


@lru_cache(maxsize=1)
def load_duckdb_auth_provider() -> DuckDBAuthProvider:
    spec = os.getenv("RETIKON_DUCKDB_AUTH_PROVIDER", "").strip()
    if not spec:
        return NoopDuckDBAuthProvider()

    module_path, sep, attr = spec.partition(":")
    if not sep or not module_path or not attr:
        raise ValueError(
            "RETIKON_DUCKDB_AUTH_PROVIDER must be in the form "
            "'module.path:ProviderClass'"
        )

    module = importlib.import_module(module_path)
    provider_obj = getattr(module, attr, None)
    if provider_obj is None:
        raise ValueError(
            f"RETIKON_DUCKDB_AUTH_PROVIDER target '{attr}' not found "
            f"in module '{module_path}'"
        )

    provider = provider_obj() if isinstance(provider_obj, type) else provider_obj
    if not hasattr(provider, "configure"):
        raise ValueError(
            "RETIKON_DUCKDB_AUTH_PROVIDER must expose a configure(conn, context) "
            "method"
        )

    logger.info(
        "DuckDB auth provider loaded",
        extra={
            "duckdb_auth_provider": f"{module_path}:{attr}",
        },
    )
    return provider
