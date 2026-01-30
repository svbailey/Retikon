from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pyarrow.parquet as pq

from retikon_core.compaction import CompactionPolicy, run_compaction
from retikon_core.retention import RetentionPolicy
from retikon_core.storage import build_manifest, manifest_uri, write_manifest
from retikon_core.storage.paths import GraphPaths
from retikon_core.storage.schemas import schema_for
from retikon_core.storage.writer import write_parquet


def _doc_rows(start: int, count: int) -> tuple[list[dict], list[dict], list[dict]]:
    core_rows: list[dict] = []
    text_rows: list[dict] = []
    vector_rows: list[dict] = []
    for idx in range(count):
        core_rows.append(
            {
                "id": str(uuid.uuid4()),
                "media_asset_id": str(uuid.uuid4()),
                "chunk_index": start + idx,
                "char_start": 0,
                "char_end": 10,
                "token_start": 0,
                "token_end": 3,
                "token_count": 3,
                "embedding_model": "stub",
                "pipeline_version": "test",
                "schema_version": "1",
            }
        )
        text_rows.append({"content": f"chunk {start + idx}"})
        vector_rows.append({"text_vector": [0.1] * 768})
    return core_rows, text_rows, vector_rows


def _write_doc_run(base_uri: str, run_id: str, start: int, count: int) -> None:
    paths = GraphPaths(base_uri=base_uri)
    core_rows, text_rows, vector_rows = _doc_rows(start, count)

    core_result = write_parquet(
        core_rows,
        schema_for("DocChunk", "core"),
        paths.vertex("DocChunk", "core", str(uuid.uuid4())),
    )
    text_result = write_parquet(
        text_rows,
        schema_for("DocChunk", "text"),
        paths.vertex("DocChunk", "text", str(uuid.uuid4())),
    )
    vector_result = write_parquet(
        vector_rows,
        schema_for("DocChunk", "vector"),
        paths.vertex("DocChunk", "vector", str(uuid.uuid4())),
    )

    started = datetime.now(timezone.utc)
    completed = datetime.now(timezone.utc)
    manifest = build_manifest(
        pipeline_version="test",
        schema_version="1",
        counts={"DocChunk": len(core_rows)},
        files=[core_result, text_result, vector_result],
        started_at=started,
        completed_at=completed,
    )
    write_manifest(manifest, manifest_uri(base_uri, run_id))


def test_compaction_merges_docchunk_runs(tmp_path):
    base_uri = tmp_path.as_posix()
    _write_doc_run(base_uri, "run-1", start=0, count=2)
    _write_doc_run(base_uri, "run-2", start=2, count=2)

    policy = CompactionPolicy(
        target_min_bytes=10_000_000,
        target_max_bytes=20_000_000,
        max_groups_per_batch=10,
    )
    report = run_compaction(
        base_uri=base_uri,
        policy=policy,
        retention_policy=RetentionPolicy(),
        delete_source=False,
        dry_run=False,
        strict=True,
    )

    assert report.manifest_uri is not None
    manifest_path = Path(report.manifest_uri)
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    output_uris = [item["uri"] for item in manifest.get("files", [])]
    assert output_uris

    core_output = next(
        output
        for output in report.outputs
        if output.entity_type == "DocChunk" and output.file_kind == "core"
    )
    core_table = pq.read_table(core_output.result.uri)
    assert core_table.num_rows == 4

    assert report.audit_uri is not None
    audit_path = Path(report.audit_uri)
    assert audit_path.exists()


def test_compaction_skips_missing_files(tmp_path, monkeypatch):
    base_uri = tmp_path.as_posix()
    _write_doc_run(base_uri, "run-1", start=0, count=2)
    _write_doc_run(base_uri, "run-2", start=2, count=2)

    manifest_path = Path(manifest_uri(base_uri, "run-1"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing_uri = (
        Path(base_uri)
        / "vertices"
        / "DocChunk"
        / "core"
        / "part-missing.parquet"
    ).as_posix()
    manifest["files"].append(
        {
            "uri": missing_uri,
            "rows": 1,
            "bytes_written": 1,
            "sha256": "",
        }
    )
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    monkeypatch.setenv("COMPACTION_SKIP_MISSING", "1")
    policy = CompactionPolicy(
        target_min_bytes=10_000_000,
        target_max_bytes=20_000_000,
        max_groups_per_batch=10,
    )
    report = run_compaction(
        base_uri=base_uri,
        policy=policy,
        retention_policy=RetentionPolicy(),
        delete_source=False,
        dry_run=False,
        strict=True,
    )

    assert report.outputs
