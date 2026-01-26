from pathlib import Path

import pytest

from retikon_core.config import get_config
from retikon_core.errors import PermanentError, RecoverableError
from retikon_core.ingestion.pipelines import audio as audio_pipeline
from retikon_core.ingestion.pipelines import video as video_pipeline
from retikon_core.ingestion.types import IngestSource


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
        "extract_frames",
        lambda _path, fps, output_dir: [str(frame_fixture), str(frame_fixture)],
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
