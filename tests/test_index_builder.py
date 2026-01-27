import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from retikon_core.errors import RecoverableError
from retikon_core.query_engine.index_builder import build_snapshot
from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import GraphPaths, edge_part_uri, manifest_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import write_parquet


def _vector(dim: int, seed: float) -> list[float]:
    return [seed] + [0.0] * (dim - 1)


def _media_row(
    *,
    media_id: str,
    uri: str,
    media_type: str,
    content_type: str,
) -> dict[str, object]:
    return {
        "id": media_id,
        "uri": uri,
        "media_type": media_type,
        "content_type": content_type,
        "size_bytes": 123,
        "source_bucket": "raw",
        "source_object": "raw/example.bin",
        "source_generation": "1",
        "checksum": None,
        "duration_ms": None,
        "width_px": None,
        "height_px": None,
        "frame_count": None,
        "sample_rate_hz": None,
        "channels": None,
        "created_at": datetime.now(timezone.utc),
        "pipeline_version": "test",
        "schema_version": "1",
    }


def _write_manifest(output_root: str, files, counts) -> None:
    started_at = datetime.now(timezone.utc)
    completed_at = datetime.now(timezone.utc)
    manifest = build_manifest(
        pipeline_version="test",
        schema_version="1",
        counts=counts,
        files=files,
        started_at=started_at,
        completed_at=completed_at,
    )
    run_id = str(uuid.uuid4())
    write_manifest(manifest, manifest_uri(output_root, run_id))


def _write_doc_run(output_root: str, paths: GraphPaths, extra_core_column: bool = False) -> None:
    media_id = str(uuid.uuid4())
    media_row = _media_row(
        media_id=media_id,
        uri="gs://raw/raw/docs/sample.pdf",
        media_type="document",
        content_type="application/pdf",
    )
    chunk_id = str(uuid.uuid4())
    chunk_core = {
        "id": chunk_id,
        "media_asset_id": media_id,
        "chunk_index": 0,
        "char_start": 0,
        "char_end": 10,
        "token_start": 0,
        "token_end": 3,
        "token_count": 3,
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    chunk_text = {"content": "hello world"}
    chunk_vector = {"text_vector": _vector(768, 1.0)}

    files = []
    files.append(
        write_parquet(
            [media_row],
            schema_for("MediaAsset", "core"),
            paths.vertex("MediaAsset", "core", str(uuid.uuid4())),
        )
    )
    if extra_core_column:
        extra_schema = schema_for("DocChunk", "core").append(
            pa.field("extra_col", pa.string(), nullable=True)
        )
        files.append(
            write_parquet(
                [dict(chunk_core, extra_col="extra")],
                extra_schema,
                paths.vertex("DocChunk", "core", str(uuid.uuid4())),
            )
        )
    else:
        files.append(
            write_parquet(
                [chunk_core],
                schema_for("DocChunk", "core"),
                paths.vertex("DocChunk", "core", str(uuid.uuid4())),
            )
        )
    files.append(
        write_parquet(
            [chunk_text],
            schema_for("DocChunk", "text"),
            paths.vertex("DocChunk", "text", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [chunk_vector],
            schema_for("DocChunk", "vector"),
            paths.vertex("DocChunk", "vector", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [{"src_id": chunk_id, "dst_id": media_id}],
            schema_for("DerivedFrom", "adj_list"),
            edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
        )
    )
    _write_manifest(
        output_root,
        files,
        {"MediaAsset": 1, "DocChunk": 1, "DerivedFrom": 1},
    )


def _write_image_run(output_root: str, paths: GraphPaths) -> None:
    media_id = str(uuid.uuid4())
    media_row = _media_row(
        media_id=media_id,
        uri="gs://raw/raw/images/sample.jpg",
        media_type="image",
        content_type="image/jpeg",
    )
    image_id = str(uuid.uuid4())
    image_core = {
        "id": image_id,
        "media_asset_id": media_id,
        "frame_index": None,
        "timestamp_ms": 0,
        "width_px": 640,
        "height_px": 480,
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    image_vector = {"clip_vector": _vector(512, 2.0)}

    files = []
    files.append(
        write_parquet(
            [media_row],
            schema_for("MediaAsset", "core"),
            paths.vertex("MediaAsset", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [image_core],
            schema_for("ImageAsset", "core"),
            paths.vertex("ImageAsset", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [image_vector],
            schema_for("ImageAsset", "vector"),
            paths.vertex("ImageAsset", "vector", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [{"src_id": image_id, "dst_id": media_id}],
            schema_for("DerivedFrom", "adj_list"),
            edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
        )
    )
    _write_manifest(
        output_root,
        files,
        {"MediaAsset": 1, "ImageAsset": 1, "DerivedFrom": 1},
    )


def _write_audio_run(output_root: str, paths: GraphPaths) -> None:
    media_id = str(uuid.uuid4())
    media_row = _media_row(
        media_id=media_id,
        uri="gs://raw/raw/audio/sample.wav",
        media_type="audio",
        content_type="audio/wav",
    )
    transcript_id = str(uuid.uuid4())
    transcript_core = {
        "id": transcript_id,
        "media_asset_id": media_id,
        "segment_index": 0,
        "start_ms": 0,
        "end_ms": 1000,
        "language": "en",
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    transcript_text = {"content": "hello"}
    transcript_vector = {"text_embedding": _vector(768, 3.0)}
    audio_id = str(uuid.uuid4())
    audio_core = {
        "id": audio_id,
        "media_asset_id": media_id,
        "start_ms": 0,
        "end_ms": 1000,
        "sample_rate_hz": 48000,
        "channels": 1,
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    audio_vector = {"clap_embedding": _vector(512, 4.0)}

    files = []
    files.append(
        write_parquet(
            [media_row],
            schema_for("MediaAsset", "core"),
            paths.vertex("MediaAsset", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [transcript_core],
            schema_for("Transcript", "core"),
            paths.vertex("Transcript", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [transcript_text],
            schema_for("Transcript", "text"),
            paths.vertex("Transcript", "text", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [transcript_vector],
            schema_for("Transcript", "vector"),
            paths.vertex("Transcript", "vector", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [audio_core],
            schema_for("AudioClip", "core"),
            paths.vertex("AudioClip", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [audio_vector],
            schema_for("AudioClip", "vector"),
            paths.vertex("AudioClip", "vector", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [
                {"src_id": transcript_id, "dst_id": media_id},
                {"src_id": audio_id, "dst_id": media_id},
            ],
            schema_for("DerivedFrom", "adj_list"),
            edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
        )
    )
    _write_manifest(
        output_root,
        files,
        {"MediaAsset": 1, "Transcript": 1, "AudioClip": 1, "DerivedFrom": 2},
    )


def test_index_builder_creates_snapshot(tmp_path):
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    output_root = str(graph_root)
    paths = GraphPaths(base_uri=output_root)

    _write_doc_run(output_root, paths)
    _write_doc_run(output_root, paths, extra_core_column=True)
    _write_image_run(output_root, paths)
    _write_audio_run(output_root, paths)

    snapshot_uri = str(tmp_path / "snapshot" / "retikon.duckdb")
    try:
        build_snapshot(
            graph_uri=output_root,
            snapshot_uri=snapshot_uri,
            work_dir=str(tmp_path / "work"),
            copy_local=False,
            fallback_local=False,
            allow_install=True,
        )
    except RecoverableError as exc:
        if "vss" in str(exc).lower():
            pytest.skip("DuckDB vss extension unavailable")
        raise

    assert Path(snapshot_uri).exists()
    assert Path(f"{snapshot_uri}.json").exists()

    report_payload = json.loads(Path(f"{snapshot_uri}.json").read_text())
    assert report_payload["tables"]["doc_chunks"]["rows"] == 2
    assert report_payload["tables"]["transcripts"]["rows"] == 1
    assert report_payload["tables"]["image_assets"]["rows"] == 1
    assert report_payload["tables"]["audio_clips"]["rows"] == 1

    conn = duckdb.connect(snapshot_uri, read_only=True)
    try:
        index_names = {
            row[0]
            for row in conn.execute(
                "SELECT index_name FROM duckdb_indexes()"
            ).fetchall()
        }
    finally:
        conn.close()

    assert "doc_chunks_text_vector" in index_names
    assert "transcripts_text_embedding" in index_names
    assert "image_assets_clip_vector" in index_names
    assert "audio_clips_clap_embedding" in index_names
