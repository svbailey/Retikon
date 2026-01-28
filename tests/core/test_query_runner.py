import base64
import os
from pathlib import Path

from retikon_core.query_engine.query_runner import (
    search_by_image,
    search_by_keyword,
    search_by_metadata,
    search_by_text,
)


def test_search_by_text_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_text(
        snapshot_path=snapshot_path,
        query_text="hello",
        top_k=3,
    )
    assert results


def test_search_by_image_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    payload = Path("tests/fixtures/sample.jpg").read_bytes()
    encoded = base64.b64encode(payload).decode("ascii")
    data_url = f"data:image/jpeg;base64,{encoded}"
    results = search_by_image(
        snapshot_path=snapshot_path,
        image_base64=data_url,
        top_k=3,
    )
    assert results


def test_search_by_keyword_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_keyword(
        snapshot_path=snapshot_path,
        query_text="hello",
        top_k=3,
    )
    assert results


def test_search_by_metadata_returns_results():
    snapshot_path = os.getenv("SNAPSHOT_URI")
    assert snapshot_path
    results = search_by_metadata(
        snapshot_path=snapshot_path,
        filters={"media_type": "image"},
        top_k=3,
    )
    assert results
