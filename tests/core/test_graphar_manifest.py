import json
from datetime import datetime, timezone

from retikon_core.storage.manifest import build_manifest, write_manifest
from retikon_core.storage.paths import manifest_uri
from retikon_core.storage.writer import WriteResult


def test_manifest_write(tmp_path):
    base_uri = tmp_path.as_posix()
    manifest_path = manifest_uri(base_uri, "run-001")
    manifest = build_manifest(
        pipeline_version="v2.5",
        schema_version="1",
        counts={"MediaAsset": 1},
        files=[
            WriteResult(
                uri="gs://retikon/vertices/MediaAsset/core/part-1.parquet",
                rows=1,
                bytes_written=123,
                sha256="abc123",
            )
        ],
        started_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        completed_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    write_manifest(manifest, manifest_path)

    with open(manifest_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)

    assert payload["pipeline_version"] == "v2.5"
    assert payload["schema_version"] == "1"
    assert payload["counts"]["MediaAsset"] == 1
    assert payload["files"][0]["sha256"] == "abc123"
