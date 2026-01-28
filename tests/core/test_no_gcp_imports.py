from __future__ import annotations

import builtins
import importlib

import pytest


@pytest.mark.core
def test_no_gcp_imports() -> None:
    real_import = builtins.__import__

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "google" or name.startswith("google.") or name.startswith("googleapiclient"):
            raise AssertionError(f"GCP import detected in Core: {name}")
        return real_import(name, globals, locals, fromlist, level)

    builtins.__import__ = guarded_import
    try:
        importlib.import_module("retikon_core")
        importlib.import_module("retikon_core.ingestion")
        importlib.import_module("retikon_core.query_engine")
    finally:
        builtins.__import__ = real_import
