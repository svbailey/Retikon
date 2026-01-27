import os
import tempfile
from pathlib import Path

import duckdb
import pytest


@pytest.fixture(autouse=True)
def _disable_query_warmup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUERY_WARMUP", "0")
    monkeypatch.setenv("LOG_QUERY_TIMINGS", "0")

    def set_default(name: str, value: str) -> None:
        if not os.getenv(name):
            monkeypatch.setenv(name, value)

    set_default("RAW_BUCKET", "test-raw")
    set_default("GRAPH_BUCKET", "test-graph")
    set_default("GRAPH_PREFIX", "retikon_v2")
    set_default("ENV", "test")
    set_default("LOG_LEVEL", "INFO")
    set_default("MAX_RAW_BYTES", "500000000")
    set_default("MAX_VIDEO_SECONDS", "300")
    set_default("MAX_AUDIO_SECONDS", "1200")
    set_default("MAX_FRAMES_PER_VIDEO", "600")
    set_default("CHUNK_TARGET_TOKENS", "512")
    set_default("CHUNK_OVERLAP_TOKENS", "50")
    set_default("INGESTION_DRY_RUN", "1")
    set_default("DUCKDB_SKIP_HEALTHCHECK", "1")
    set_default("DUCKDB_ALLOW_INSTALL", "1")
    set_default("SNAPSHOT_URI", _ensure_test_snapshot())


_TEST_SNAPSHOT_PATH: str | None = None


def _ensure_test_snapshot() -> str:
    global _TEST_SNAPSHOT_PATH
    if _TEST_SNAPSHOT_PATH and Path(_TEST_SNAPSHOT_PATH).exists():
        return _TEST_SNAPSHOT_PATH

    base_dir = Path(tempfile.mkdtemp(prefix="retikon_test_snapshot_"))
    snapshot_path = base_dir / "retikon_test.duckdb"

    vec_768 = [0.1] * 768
    vec_512 = [0.1] * 512

    conn = duckdb.connect(str(snapshot_path))
    conn.execute(
        """
        CREATE TABLE media_assets (
            id VARCHAR,
            uri VARCHAR,
            media_type VARCHAR,
            content_type VARCHAR,
            org_id VARCHAR,
            site_id VARCHAR,
            stream_id VARCHAR
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE doc_chunks (
            media_asset_id VARCHAR,
            content VARCHAR,
            text_vector FLOAT[]
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE transcripts (
            media_asset_id VARCHAR,
            content VARCHAR,
            start_ms BIGINT,
            text_embedding FLOAT[]
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE image_assets (
            media_asset_id VARCHAR,
            timestamp_ms BIGINT,
            thumbnail_uri VARCHAR,
            clip_vector FLOAT[]
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE audio_clips (
            media_asset_id VARCHAR,
            clap_embedding FLOAT[]
        )
        """
    )

    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "asset-doc",
            "gs://test/doc.pdf",
            "document",
            "application/pdf",
            "org-1",
            "site-1",
            "stream-1",
        ],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "asset-transcript",
            "gs://test/video.mp4",
            "video",
            "video/mp4",
            "org-1",
            "site-2",
            "stream-2",
        ],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "asset-image",
            "gs://test/image.jpg",
            "image",
            "image/jpeg",
            "org-2",
            "site-2",
            "stream-3",
        ],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            "asset-audio",
            "gs://test/audio.wav",
            "audio",
            "audio/wav",
            "org-1",
            "site-3",
            "stream-4",
        ],
    )
    conn.execute(
        "INSERT INTO doc_chunks VALUES (?, ?, ?)",
        ["asset-doc", "hello world", vec_768],
    )
    conn.execute(
        "INSERT INTO transcripts VALUES (?, ?, ?, ?)",
        ["asset-transcript", "hello transcript", 0, vec_768],
    )
    conn.execute(
        "INSERT INTO image_assets VALUES (?, ?, ?, ?)",
        ["asset-image", 0, "gs://test/thumb.jpg", vec_512],
    )
    conn.execute(
        "INSERT INTO audio_clips VALUES (?, ?)",
        ["asset-audio", vec_512],
    )
    conn.close()

    _TEST_SNAPSHOT_PATH = str(snapshot_path)
    return _TEST_SNAPSHOT_PATH
