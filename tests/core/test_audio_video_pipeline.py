import json
import uuid
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from retikon_core.config import get_config
from retikon_core.errors import PermanentError, RecoverableError
from retikon_core.ingestion.media import FrameInfo
from retikon_core.ingestion.pipelines import audio as audio_pipeline
from retikon_core.ingestion.pipelines import video as video_pipeline
from retikon_core.ingestion.types import IngestSource


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def test_audio_pipeline_writes_graphar(tmp_path, monkeypatch):
    config = get_config()
    fixture = Path("tests/fixtures/sample.wav")

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": 1.0,
                "has_audio": True,
                "has_video": False,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": None,
                "video_height": None,
                "frame_rate": None,
                "frame_count": None,
            },
        )()

    monkeypatch.setattr(audio_pipeline, "probe_media", fake_probe)
    monkeypatch.setattr(
        audio_pipeline,
        "normalize_audio",
        lambda _path, sample_rate=48000: str(fixture),
    )

    source = IngestSource(
        bucket="test-raw",
        name="raw/audio/sample.wav",
        generation="1",
        content_type="audio/wav",
        size_bytes=fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(fixture),
    )

    result = audio_pipeline.ingest_audio(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    assert result.counts["AudioClip"] == 1

    payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
    files = [item["uri"] for item in payload.get("files", [])]
    media_uri = next(uri for uri in files if "vertices/MediaAsset/core" in uri)
    transcript_core_uri = next(
        uri for uri in files if "vertices/Transcript/core" in uri
    )
    audio_core_uri = next(uri for uri in files if "vertices/AudioClip/core" in uri)
    edge_uri = next(uri for uri in files if "edges/DerivedFrom/adj_list" in uri)

    media_table = pq.read_table(media_uri)
    transcript_table = pq.read_table(transcript_core_uri)
    audio_table = pq.read_table(audio_core_uri)
    edge_table = pq.read_table(edge_uri)

    for value in media_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in transcript_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in transcript_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in audio_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in audio_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("src_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("dst_id").to_pylist():
        assert _is_uuid4(value)


def test_audio_pipeline_empty_transcript_skips_embeddings(tmp_path, monkeypatch):
    config = get_config()
    fixture = Path("tests/fixtures/sample.wav")

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": 1.0,
                "has_audio": True,
                "has_video": False,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": None,
                "video_height": None,
                "frame_rate": None,
                "frame_count": None,
            },
        )()

    def raise_embedder(_dim):
        raise AssertionError("Text embedder should not be called for empty transcript")

    monkeypatch.setattr(audio_pipeline, "probe_media", fake_probe)
    monkeypatch.setattr(
        audio_pipeline,
        "normalize_audio",
        lambda _path, sample_rate=48000: str(fixture),
    )
    monkeypatch.setattr(audio_pipeline, "transcribe_audio", lambda *_: [])
    monkeypatch.setattr(audio_pipeline, "get_text_embedder", raise_embedder)

    source = IngestSource(
        bucket="test-raw",
        name="raw/audio/sample.wav",
        generation="1",
        content_type="audio/wav",
        size_bytes=fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(fixture),
    )

    result = audio_pipeline.ingest_audio(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    assert result.counts["Transcript"] == 0


def test_audio_duration_cap(monkeypatch):
    config = get_config()

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": config.max_audio_seconds + 1,
                "has_audio": True,
                "has_video": False,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": None,
                "video_height": None,
                "frame_rate": None,
                "frame_count": None,
            },
        )()

    monkeypatch.setattr(audio_pipeline, "probe_media", fake_probe)
    source = IngestSource(
        bucket="test-raw",
        name="raw/audio/too-long.wav",
        generation="1",
        content_type="audio/wav",
        size_bytes=1,
        md5_hash=None,
        crc32c=None,
        local_path="dummy",
    )
    with pytest.raises(PermanentError):
        audio_pipeline.ingest_audio(
            source=source,
            config=config,
            output_uri=None,
            pipeline_version="v2.5",
            schema_version="1",
        )


def test_audio_corrupt_file(monkeypatch):
    config = get_config()

    def fake_probe(_path):
        raise RecoverableError("ffprobe failed")

    monkeypatch.setattr(audio_pipeline, "probe_media", fake_probe)
    source = IngestSource(
        bucket="test-raw",
        name="raw/audio/bad.wav",
        generation="1",
        content_type="audio/wav",
        size_bytes=1,
        md5_hash=None,
        crc32c=None,
        local_path="dummy",
    )
    with pytest.raises(RecoverableError):
        audio_pipeline.ingest_audio(
            source=source,
            config=config,
            output_uri=None,
            pipeline_version="v2.5",
            schema_version="1",
        )


def test_video_pipeline_writes_graphar(tmp_path, monkeypatch):
    config = get_config()
    video_fixture = Path("tests/fixtures/sample.mp4")
    frame_fixture = Path("tests/fixtures/sample.jpg")
    audio_fixture = Path("tests/fixtures/sample.wav")

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": 1.0,
                "has_audio": True,
                "has_video": True,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": 2,
                "video_height": 2,
                "frame_rate": 1.0,
                "frame_count": 2,
            },
        )()

    monkeypatch.setattr(video_pipeline, "probe_media", fake_probe)
    monkeypatch.setattr(
        video_pipeline,
        "extract_keyframes",
        lambda *args, **kwargs: [
            FrameInfo(path=str(frame_fixture), timestamp_ms=0),
            FrameInfo(path=str(frame_fixture), timestamp_ms=1000),
        ],
    )
    monkeypatch.setattr(
        video_pipeline,
        "extract_audio",
        lambda _path, sample_rate=48000: str(audio_fixture),
    )
    monkeypatch.setattr(video_pipeline, "cleanup_tmp", lambda _path: None)

    source = IngestSource(
        bucket="test-raw",
        name="raw/videos/sample.mp4",
        generation="1",
        content_type="video/mp4",
        size_bytes=video_fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(video_fixture),
    )

    result = video_pipeline.ingest_video(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    assert result.counts["ImageAsset"] == 2

    payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
    files = [item["uri"] for item in payload.get("files", [])]
    media_uri = next(uri for uri in files if "vertices/MediaAsset/core" in uri)
    image_core_uri = next(uri for uri in files if "vertices/ImageAsset/core" in uri)
    transcript_core_uri = next(
        uri for uri in files if "vertices/Transcript/core" in uri
    )
    audio_core_uri = next(uri for uri in files if "vertices/AudioClip/core" in uri)
    edge_uri = next(uri for uri in files if "edges/DerivedFrom/adj_list" in uri)

    media_table = pq.read_table(media_uri)
    image_table = pq.read_table(image_core_uri)
    transcript_table = pq.read_table(transcript_core_uri)
    audio_table = pq.read_table(audio_core_uri)
    edge_table = pq.read_table(edge_uri)

    for value in media_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in image_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in image_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in transcript_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in transcript_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in audio_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in audio_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("src_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("dst_id").to_pylist():
        assert _is_uuid4(value)


def test_video_pipeline_empty_transcript_skips_embeddings(tmp_path, monkeypatch):
    config = get_config()
    video_fixture = Path("tests/fixtures/sample.mp4")
    frame_fixture = Path("tests/fixtures/sample.jpg")
    audio_fixture = Path("tests/fixtures/sample.wav")

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": 1.0,
                "has_audio": True,
                "has_video": True,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": 2,
                "video_height": 2,
                "frame_rate": 1.0,
                "frame_count": 2,
            },
        )()

    def raise_embedder(_dim):
        raise AssertionError("Text embedder should not be called for empty transcript")

    monkeypatch.setattr(video_pipeline, "probe_media", fake_probe)
    monkeypatch.setattr(
        video_pipeline,
        "extract_keyframes",
        lambda *args, **kwargs: [
            FrameInfo(path=str(frame_fixture), timestamp_ms=0),
            FrameInfo(path=str(frame_fixture), timestamp_ms=1000),
        ],
    )
    monkeypatch.setattr(
        video_pipeline,
        "extract_audio",
        lambda _path, sample_rate=48000: str(audio_fixture),
    )
    monkeypatch.setattr(video_pipeline, "cleanup_tmp", lambda _path: None)
    monkeypatch.setattr(video_pipeline, "transcribe_audio", lambda *_: [])
    monkeypatch.setattr(video_pipeline, "get_text_embedder", raise_embedder)

    source = IngestSource(
        bucket="test-raw",
        name="raw/videos/sample.mp4",
        generation="1",
        content_type="video/mp4",
        size_bytes=video_fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(video_fixture),
    )

    result = video_pipeline.ingest_video(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    assert result.counts["Transcript"] == 0


def test_video_duration_cap(monkeypatch):
    config = get_config()

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": config.max_video_seconds + 1,
                "has_audio": True,
                "has_video": True,
                "audio_sample_rate": 48000,
                "audio_channels": 1,
                "video_width": 2,
                "video_height": 2,
                "frame_rate": 1.0,
                "frame_count": 2,
            },
        )()

    monkeypatch.setattr(video_pipeline, "probe_media", fake_probe)
    source = IngestSource(
        bucket="test-raw",
        name="raw/videos/too-long.mp4",
        generation="1",
        content_type="video/mp4",
        size_bytes=1,
        md5_hash=None,
        crc32c=None,
        local_path="dummy",
    )
    with pytest.raises(PermanentError):
        video_pipeline.ingest_video(
            source=source,
            config=config,
            output_uri=None,
            pipeline_version="v2.5",
            schema_version="1",
        )


def test_video_corrupt_file(monkeypatch):
    config = get_config()

    def fake_probe(_path):
        raise RecoverableError("ffprobe failed")

    monkeypatch.setattr(video_pipeline, "probe_media", fake_probe)
    source = IngestSource(
        bucket="test-raw",
        name="raw/videos/bad.mp4",
        generation="1",
        content_type="video/mp4",
        size_bytes=1,
        md5_hash=None,
        crc32c=None,
        local_path="dummy",
    )
    with pytest.raises(RecoverableError):
        video_pipeline.ingest_video(
            source=source,
            config=config,
            output_uri=None,
            pipeline_version="v2.5",
            schema_version="1",
        )


def test_video_frame_cap(monkeypatch):
    from retikon_core import config as config_module

    monkeypatch.setenv("MAX_FRAMES_PER_VIDEO", "2")
    config_module.get_config.cache_clear()
    config = config_module.get_config()

    def fake_probe(_path):
        return type(
            "Probe",
            (),
            {
                "duration_seconds": 10.0,
                "has_audio": False,
                "has_video": True,
                "audio_sample_rate": None,
                "audio_channels": None,
                "video_width": 2,
                "video_height": 2,
                "frame_rate": 1.0,
                "frame_count": 10,
            },
        )()

    monkeypatch.setattr(video_pipeline, "probe_media", fake_probe)
    source = IngestSource(
        bucket="test-raw",
        name="raw/videos/too-many-frames.mp4",
        generation="1",
        content_type="video/mp4",
        size_bytes=1,
        md5_hash=None,
        crc32c=None,
        local_path="dummy",
    )
    with pytest.raises(PermanentError):
        video_pipeline.ingest_video(
            source=source,
            config=config,
            output_uri=None,
            pipeline_version="v2.5",
            schema_version="1",
        )
