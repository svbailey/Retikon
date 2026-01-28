import os

os.environ.setdefault("QUERY_TIER_OVERRIDE", "gpu")
os.environ.setdefault("EMBEDDING_DEVICE", "cuda")

from gcp_adapter.query_service import app  # noqa: E402

__all__ = ["app"]
