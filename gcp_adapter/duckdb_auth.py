from __future__ import annotations

import os

import duckdb

from retikon_core.query_engine.duckdb_auth import DuckDBAuthContext
from retikon_core.query_engine.warm_start import load_extensions


def _is_gcs_uri(uri: str) -> bool:
    return uri.startswith("gs://")


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
            load_extensions(conn, ("gcs",), context.allow_install)
            return "gcs_extension", True

        conn.execute("CREATE SECRET retikon_gcs (TYPE GCS, PROVIDER credential_chain)")
        return "credential_chain", False
