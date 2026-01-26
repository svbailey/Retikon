import duckdb
import pytest

_SNAPSHOT_PATH = None


def _build_snapshot(path):
    text_vec = [0.0] * 768
    text_vec[0] = 1.0
    clip_vec = [0.0] * 512
    clip_vec[0] = 1.0

    conn = duckdb.connect(str(path))
    conn.execute(
        "CREATE TABLE media_assets (id VARCHAR, uri VARCHAR, media_type VARCHAR)"
    )
    conn.execute(
        "CREATE TABLE doc_chunks ("
        "media_asset_id VARCHAR, "
        "content VARCHAR, "
        "text_vector FLOAT[]"
        ")"
    )
    conn.execute(
        "CREATE TABLE transcripts ("
        "media_asset_id VARCHAR, "
        "content VARCHAR, "
        "start_ms BIGINT, "
        "text_embedding FLOAT[]"
        ")"
    )
    conn.execute(
        "CREATE TABLE image_assets ("
        "media_asset_id VARCHAR, "
        "timestamp_ms BIGINT, "
        "clip_vector FLOAT[]"
        ")"
    )
    conn.execute(
        "CREATE TABLE audio_clips (media_asset_id VARCHAR, clap_embedding FLOAT[])"
    )

    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?)",
        ["media-1", "gs://test-raw/raw/docs/sample.pdf", "document"],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?)",
        ["media-2", "gs://test-raw/raw/images/sample.jpg", "image"],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?)",
        ["media-3", "gs://test-raw/raw/audio/sample.mp3", "audio"],
    )
    conn.execute(
        "INSERT INTO media_assets VALUES (?, ?, ?)",
        ["media-4", "gs://test-raw/raw/videos/sample.mp4", "video"],
    )
    conn.execute(
        "INSERT INTO doc_chunks VALUES (?, ?, ?)",
        ["media-1", "Hello world", text_vec],
    )
    conn.execute(
        "INSERT INTO transcripts VALUES (?, ?, ?, ?)",
        ["media-4", "hello transcript", 1200, text_vec],
    )
    conn.execute(
        "INSERT INTO image_assets VALUES (?, ?, ?)",
        ["media-2", 0, clip_vec],
    )
    conn.execute(
        "INSERT INTO audio_clips VALUES (?, ?)",
        ["media-3", clip_vec],
    )
    conn.close()


@pytest.fixture(autouse=True)
def _set_env(monkeypatch, tmp_path_factory):
    global _SNAPSHOT_PATH
    if _SNAPSHOT_PATH is None:
        path = tmp_path_factory.mktemp("snapshot") / "retikon-test.duckdb"
        _build_snapshot(path)
        _SNAPSHOT_PATH = path

    monkeypatch.setenv("RAW_BUCKET", "test-raw")
    monkeypatch.setenv("GRAPH_BUCKET", "test-graph")
    monkeypatch.setenv("GRAPH_PREFIX", "retikon_v2")
    monkeypatch.setenv("ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("MAX_RAW_BYTES", "500000000")
    monkeypatch.setenv("MAX_VIDEO_SECONDS", "300")
    monkeypatch.setenv("MAX_AUDIO_SECONDS", "1200")
    monkeypatch.setenv("CHUNK_TARGET_TOKENS", "512")
    monkeypatch.setenv("CHUNK_OVERLAP_TOKENS", "50")
    monkeypatch.setenv("INGESTION_DRY_RUN", "1")
    monkeypatch.setenv("VIDEO_SAMPLE_FPS", "1.0")
    monkeypatch.setenv("VIDEO_SAMPLE_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("SNAPSHOT_URI", str(_SNAPSHOT_PATH))
    monkeypatch.setenv("DUCKDB_SKIP_HEALTHCHECK", "1")
    monkeypatch.setenv("DUCKDB_ALLOW_INSTALL", "1")
