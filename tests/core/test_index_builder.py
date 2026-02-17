import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import pyarrow as pa
import pytest

from retikon_core.errors import RecoverableError
from retikon_core.query_engine import index_builder
from retikon_core.query_engine.index_builder import build_snapshot
from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import GraphPaths, edge_part_uri, manifest_uri
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import write_parquet


def _vector(dim: int, seed: float) -> list[float]:
    return [seed] + [0.0] * (dim - 1)


def _assert_index_timing_sum(report_payload: dict[str, object]) -> None:
    duration = report_payload.get("duration_seconds")
    assert isinstance(duration, (int, float))
    required_fields = (
        "apply_deltas_seconds",
        "build_vectors_seconds",
        "write_snapshot_seconds",
    )
    for key in required_fields:
        value = report_payload.get(key)
        assert isinstance(value, (int, float))
    timing_fields = (
        "snapshot_download_seconds",
        "load_snapshot_seconds",
        "apply_deltas_seconds",
        "build_vectors_seconds",
        "write_snapshot_seconds",
    )
    timed_total = 0.0
    for key in timing_fields:
        value = report_payload.get(key)
        if value is None:
            continue
        assert isinstance(value, (int, float))
        timed_total += float(value)
    assert timed_total > 0
    tolerance = max(2.0, duration * 0.2)
    assert abs(duration - timed_total) <= tolerance


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


def _write_manifest(output_root: str, files, counts, run_id: str | None = None) -> None:
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
    run_id = run_id or str(uuid.uuid4())
    write_manifest(manifest, manifest_uri(output_root, run_id))


def _write_doc_run(
    output_root: str,
    paths: GraphPaths,
    extra_core_column: bool = False,
    *,
    source_type: str | None = None,
    source_ref_id: str | int | None = None,
    source_time_ms: int | None = None,
    ocr_conf_avg: int | None = None,
    legacy_source_ref_int: bool = False,
) -> None:
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
    if source_type is not None:
        chunk_core["source_type"] = source_type
    if source_ref_id is not None:
        chunk_core["source_ref_id"] = source_ref_id
    if source_time_ms is not None:
        chunk_core["source_time_ms"] = source_time_ms
    if ocr_conf_avg is not None:
        chunk_core["ocr_conf_avg"] = ocr_conf_avg
    chunk_text = {"content": "hello world"}
    chunk_vector = {"text_vector": _vector(768, 1.0)}

    core_schema = schema_for("DocChunk", "core")
    if legacy_source_ref_int:
        legacy_fields: list[pa.Field] = []
        for field in core_schema:
            if field.name == "source_ref_id":
                legacy_fields.append(pa.field("source_ref_id", pa.int32(), nullable=True))
            else:
                legacy_fields.append(field)
        core_schema = pa.schema(legacy_fields)

    files = []
    files.append(
        write_parquet(
            [media_row],
            schema_for("MediaAsset", "core"),
            paths.vertex("MediaAsset", "core", str(uuid.uuid4())),
        )
    )
    if extra_core_column:
        extra_schema = core_schema.append(pa.field("extra_col", pa.string(), nullable=True))
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
                core_schema,
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
            [
                {
                    "src_id": chunk_id,
                    "dst_id": media_id,
                    "schema_version": "1",
                }
            ],
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
        "embedding_model_v2": "siglip2",
        "embedding_backend_v2": "stub",
        "embedding_artifact_v2": "stub:deterministic",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    image_vector = {"clip_vector": _vector(512, 2.0), "vision_vector_v2": _vector(768, 3.0)}

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
            [
                {
                    "src_id": image_id,
                    "dst_id": media_id,
                    "schema_version": "1",
                }
            ],
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
    audio_segment_id = str(uuid.uuid4())
    audio_segment_core = {
        "id": audio_segment_id,
        "media_asset_id": media_id,
        "start_ms": 0,
        "end_ms": 500,
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    audio_segment_vector = {"clap_embedding": _vector(512, 4.1)}

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
            [audio_segment_core],
            schema_for("AudioSegment", "core"),
            paths.vertex("AudioSegment", "core", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [audio_segment_vector],
            schema_for("AudioSegment", "vector"),
            paths.vertex("AudioSegment", "vector", str(uuid.uuid4())),
        )
    )
    files.append(
        write_parquet(
            [
                {"src_id": transcript_id, "dst_id": media_id, "schema_version": "1"},
                {"src_id": audio_id, "dst_id": media_id, "schema_version": "1"},
                {"src_id": audio_segment_id, "dst_id": media_id, "schema_version": "1"},
            ],
            schema_for("DerivedFrom", "adj_list"),
            edge_part_uri(output_root, "DerivedFrom", str(uuid.uuid4())),
        )
    )
    _write_manifest(
        output_root,
        files,
        {
            "MediaAsset": 1,
            "Transcript": 1,
            "AudioClip": 1,
            "AudioSegment": 1,
            "DerivedFrom": 3,
        },
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
    assert report_payload["tables"]["audio_segments"]["rows"] == 1
    assert report_payload["manifest_count"] > 0
    assert report_payload["snapshot_manifest_count"] == report_payload["manifest_count"]
    assert report_payload["index_queue_length"] == 0
    assert report_payload["manifest_fingerprint"]
    _assert_index_timing_sum(report_payload)
    index_dims = {
        "doc_chunks_text_vector": 768,
        "transcripts_text_embedding": 768,
        "image_assets_clip_vector": 512,
        "image_assets_vision_vector_v2": 768,
        "audio_clips_clap_embedding": 512,
        "audio_segments_clap_embedding": 512,
    }
    for index_name, dim in index_dims.items():
        info = report_payload["indexes"][index_name]
        assert info["dim"] == dim
        assert info["ef_construction"] == 200
        assert info["m"] == 16

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
    assert "image_assets_vision_vector_v2" in index_names
    assert "audio_clips_clap_embedding" in index_names
    assert "audio_segments_clap_embedding" in index_names


def test_index_builder_parses_remote_uri():
    scheme, container, path = index_builder._parse_remote_uri(
        "s3://retikon-graph/retikon_v2"
    )
    assert scheme == "s3"
    assert container == "retikon-graph"
    assert path == "retikon_v2"


def test_index_builder_rewrites_manifest_uris_for_duckdb(tmp_path, monkeypatch):
    monkeypatch.setenv("DUCKDB_GCS_URI_SCHEME", "gcs")
    manifest = {
        "pipeline_version": "test",
        "schema_version": "1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "counts": {"ImageAsset": 1, "MediaAsset": 1},
        "files": [
            {
                "uri": "gs://bucket/retikon_v2/vertices/MediaAsset/core/part-media.parquet",
                "rows": 1,
                "bytes_written": 1,
                "sha256": "deadbeef",
            },
            {
                "uri": "gs://bucket/retikon_v2/vertices/ImageAsset/core/part-core.parquet",
                "rows": 1,
                "bytes_written": 1,
                "sha256": "deadbeef",
            },
            {
                "uri": "gs://bucket/retikon_v2/vertices/ImageAsset/vector/part-vector.parquet",
                "rows": 1,
                "bytes_written": 1,
                "sha256": "deadbeef",
            },
        ],
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    groups, media_files, has_manifests, *_ = index_builder._load_manifest_groups(
        base_uri=str(tmp_path),
        manifest_uris=[str(manifest_path)],
    )

    assert has_manifests is True
    assert media_files[0].startswith("gcs://")
    image_group = groups["ImageAsset"][0]
    assert image_group.core.startswith("gcs://")
    assert image_group.vector.startswith("gcs://")


def test_index_builder_skips_when_manifests_unchanged(tmp_path):
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    output_root = str(graph_root)
    paths = GraphPaths(base_uri=output_root)

    _write_doc_run(output_root, paths)

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

    before_mtime = Path(snapshot_uri).stat().st_mtime

    report = build_snapshot(
        graph_uri=output_root,
        snapshot_uri=snapshot_uri,
        work_dir=str(tmp_path / "work"),
        copy_local=False,
        fallback_local=False,
        allow_install=True,
        skip_if_unchanged=True,
    )

    assert report.skipped is True
    assert Path(snapshot_uri).stat().st_mtime == before_mtime


def test_index_builder_incremental_appends(tmp_path):
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    output_root = str(graph_root)
    paths = GraphPaths(base_uri=output_root)

    _write_doc_run(output_root, paths)

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

    _write_doc_run(output_root, paths)

    report = build_snapshot(
        graph_uri=output_root,
        snapshot_uri=snapshot_uri,
        work_dir=str(tmp_path / "work2"),
        copy_local=False,
        fallback_local=False,
        allow_install=True,
        incremental=True,
    )

    assert report.new_manifest_count == 1
    assert report.tables["doc_chunks"]["rows"] == 2
    assert report.snapshot_manifest_count == report.manifest_count
    assert report.index_queue_length == 0


def test_index_builder_incremental_promotes_legacy_source_ref_id_type(tmp_path):
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    output_root = str(graph_root)
    paths = GraphPaths(base_uri=output_root)

    # Simulate a legacy snapshot with integer source_ref_id values.
    _write_doc_run(
        output_root,
        paths,
        source_type="document",
        source_ref_id=12345,
        legacy_source_ref_int=True,
    )

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

    source_ref = str(uuid.uuid4())
    _write_doc_run(
        output_root,
        paths,
        source_type="image",
        source_ref_id=source_ref,
    )

    report = build_snapshot(
        graph_uri=output_root,
        snapshot_uri=snapshot_uri,
        work_dir=str(tmp_path / "work2"),
        copy_local=False,
        fallback_local=False,
        allow_install=True,
        incremental=True,
    )

    assert report.new_manifest_count == 1
    conn = duckdb.connect(snapshot_uri)
    try:
        schema_rows = conn.execute("PRAGMA table_info('doc_chunks')").fetchall()
        type_by_name = {str(row[1]): str(row[2]) for row in schema_rows}
        assert type_by_name["source_ref_id"] == "VARCHAR"
        row = conn.execute(
            "SELECT source_ref_id FROM doc_chunks "
            "WHERE source_type = 'image' ORDER BY source_ref_id DESC LIMIT 1"
        ).fetchone()
        assert row is not None
        assert row[0] == source_ref
    finally:
        conn.close()


def test_index_builder_uses_latest_compaction(tmp_path):
    graph_root = tmp_path / "graph"
    graph_root.mkdir()
    output_root = str(graph_root)
    paths = GraphPaths(base_uri=output_root)

    _write_doc_run(output_root, paths)
    _write_doc_run(output_root, paths)

    media_id = str(uuid.uuid4())
    media_row = _media_row(
        media_id=media_id,
        uri="gs://raw/raw/docs/compacted.pdf",
        media_type="document",
        content_type="application/pdf",
    )
    chunk_id = str(uuid.uuid4())
    chunk_core = {
        "id": chunk_id,
        "media_asset_id": media_id,
        "chunk_index": 0,
        "char_start": 0,
        "char_end": 8,
        "token_start": 0,
        "token_end": 2,
        "token_count": 2,
        "embedding_model": "stub",
        "pipeline_version": "test",
        "schema_version": "1",
    }
    chunk_text = {"content": "compact"}
    chunk_vector = {"text_vector": _vector(768, 9.0)}

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
    _write_manifest(
        output_root,
        files,
        {"MediaAsset": 1, "DocChunk": 1},
        run_id="compaction-test",
    )

    snapshot_uri = str(tmp_path / "snapshot" / "retikon.duckdb")
    try:
        report = build_snapshot(
            graph_uri=output_root,
            snapshot_uri=snapshot_uri,
            work_dir=str(tmp_path / "work"),
            copy_local=False,
            fallback_local=False,
            allow_install=True,
            use_latest_compaction=True,
        )
    except RecoverableError as exc:
        if "vss" in str(exc).lower():
            pytest.skip("DuckDB vss extension unavailable")
        raise

    assert report.tables["doc_chunks"]["rows"] == 1


def test_index_builder_skip_missing_files(tmp_path):
    output_root = tmp_path / "graph"
    output_root.mkdir()
    run_id = str(uuid.uuid4())
    missing_uri = str(
        GraphPaths(str(output_root)).vertex("MediaAsset", "core", str(uuid.uuid4()))
    )
    manifest = {
        "pipeline_version": "test",
        "schema_version": "1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "counts": {},
        "files": [
            {
                "uri": missing_uri,
                "rows": 0,
                "bytes_written": 0,
                "sha256": "",
            }
        ],
    }
    write_manifest(manifest, manifest_uri(str(output_root), run_id))

    snapshot_uri = str(output_root / "snapshots" / "retikon.duckdb")
    report = build_snapshot(
        graph_uri=str(output_root),
        snapshot_uri=snapshot_uri,
        work_dir=str(tmp_path / "work"),
        copy_local=False,
        fallback_local=False,
        allow_install=False,
        skip_missing_files=True,
    )
    assert report.tables["media_assets"]["rows"] == 0
