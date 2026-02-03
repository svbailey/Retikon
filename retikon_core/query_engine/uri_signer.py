from __future__ import annotations

import importlib
import os
from typing import Callable

from retikon_core.errors import RecoverableError
from retikon_core.logging import get_logger

logger = get_logger(__name__)

DuckDBUriSigner = Callable[[str], str]

_SIGNER: DuckDBUriSigner | None = None


def _default_signer(uri: str) -> str:
    return uri


def load_duckdb_uri_signer() -> DuckDBUriSigner:
    global _SIGNER
    if _SIGNER is not None:
        return _SIGNER
    spec = os.getenv("RETIKON_DUCKDB_URI_SIGNER", "").strip()
    if not spec:
        _SIGNER = _default_signer
        return _SIGNER
    module_path, _, attr = spec.partition(":")
    if not module_path or not attr:
        raise RecoverableError(
            "RETIKON_DUCKDB_URI_SIGNER must be in the form module.path:callable"
        )
    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise RecoverableError(
            f"Failed to import DuckDB URI signer module '{module_path}': {exc}"
        ) from exc
    signer = getattr(module, attr, None)
    if signer is None or not callable(signer):
        raise RecoverableError(
            f"RETIKON_DUCKDB_URI_SIGNER target '{attr}' not found or not callable"
        )
    logger.info(
        "DuckDB URI signer loaded",
        extra={"duckdb_uri_signer": f"{module_path}:{attr}"},
    )
    _SIGNER = signer
    return _SIGNER
