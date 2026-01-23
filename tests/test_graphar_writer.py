from datetime import datetime

import pyarrow.parquet as pq

from retikon_core.storage.paths import vertex_part_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import write_parquet


def _vector(length: int) -> list[float]:
    return [0.01] * length


def test_write_parquet_roundtrip(tmp_path):
    base_uri = tmp_path.as_posix()

    cases = [
        (
            "MediaAsset",
            "core",
            {
                "id": "media-1",
                "uri": "gs://retikon/raw/file.pdf",
                "media_type": "document",
                "content_type": "application/pdf",
                "size_bytes": 123,
                "source_bucket": "retikon-raw",
                "source_object": "raw/file.pdf",
                "source_generation": "1",
                "checksum": None,
                "duration_ms": None,
                "width_px": None,
                "height_px": None,
                "frame_count": None,
                "sample_rate_hz": None,
                "channels": None,
                "created_at": datetime(2024, 1, 1),
                "pipeline_version": "v2.5",
                "schema_version": "1",
            },
        ),
        (
            "DocChunk",
            "core",
            {
                "id": "chunk-1",
                "media_asset_id": "media-1",
                "chunk_index": 0,
                "char_start": 0,
                "char_end": 10,
                "token_start": 0,
                "token_end": 5,
                "token_count": 5,
                "embedding_model": "bge-base",
                "pipeline_version": "v2.5",
                "schema_version": "1",
            },
        ),
        ("DocChunk", "text", {"content": "hello"}),
        ("DocChunk", "vector", {"text_vector": _vector(768)}),
        (
            "ImageAsset",
            "core",
            {
                "id": "img-1",
                "media_asset_id": "media-2",
                "frame_index": None,
                "timestamp_ms": None,
                "width_px": 2,
                "height_px": 2,
                "embedding_model": "clip-vit-b-32",
                "pipeline_version": "v2.5",
                "schema_version": "1",
            },
        ),
        ("ImageAsset", "vector", {"clip_vector": _vector(512)}),
        (
            "Transcript",
            "core",
            {
                "id": "tr-1",
                "media_asset_id": "media-3",
                "segment_index": 0,
                "start_ms": 0,
                "end_ms": 1000,
                "language": "en",
                "embedding_model": "bge-base",
                "pipeline_version": "v2.5",
                "schema_version": "1",
            },
        ),
        ("Transcript", "text", {"content": "hello world"}),
        ("Transcript", "vector", {"text_embedding": _vector(768)}),
        (
            "AudioClip",
            "core",
            {
                "id": "audio-1",
                "media_asset_id": "media-4",
                "start_ms": 0,
                "end_ms": 1000,
                "sample_rate_hz": 48000,
                "channels": 1,
                "embedding_model": "clap",
                "pipeline_version": "v2.5",
                "schema_version": "1",
            },
        ),
        ("AudioClip", "vector", {"clap_embedding": _vector(512)}),
    ]

    for entity, file_kind, row in cases:
        schema = schema_for(entity, file_kind)
        dest_uri = vertex_part_uri(base_uri, entity, file_kind, f"{entity}-{file_kind}")
        result = write_parquet([row], schema, dest_uri, compression="none")
        assert result.rows == 1
        table = pq.read_table(dest_uri)
        assert table.schema.equals(schema, check_metadata=False)
