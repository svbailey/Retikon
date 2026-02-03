from __future__ import annotations

import os

import duckdb

from retikon_core.errors import RecoverableError
from retikon_core.query_engine.duckdb_auth import DuckDBAuthContext


def _is_gcs_uri(uri: str) -> bool:
    return uri.startswith("gs://")


def _load_community_extension(
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
            conn.execute(f"INSTALL {name} FROM community")
            conn.execute(f"LOAD {name}")
        except Exception as install_exc:
            raise RecoverableError(
                f"DuckDB INSTALL/LOAD {name} failed: {install_exc}"
            ) from install_exc


class GcsDuckDBAuthProvider:
    def configure(
        self,
        conn: duckdb.DuckDBPyConnection,
        context: DuckDBAuthContext,
    ) -> tuple[str, bool]:
        if not any(_is_gcs_uri(uri) for uri in context.uris):
            return "none", False

        conn.execute("DROP SECRET IF EXISTS retikon_gcs")
        use_fallback = os.getenv("DUCKDB_GCS_FALLBACK", "0") == "1"
        if use_fallback:
            _load_community_extension(conn, "gcs", context.allow_install)
            conn.execute(
                "CREATE SECRET retikon_gcs (TYPE gcp, PROVIDER credential_chain)"
            )
            os.environ.setdefault("DUCKDB_GCS_URI_SCHEME", "gcss")
            return "gcs_extension", True

        conn.execute("CREATE SECRET retikon_gcs (TYPE GCS, PROVIDER credential_chain)")
        return "credential_chain", False
