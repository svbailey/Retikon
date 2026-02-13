import json
import uuid
from pathlib import Path

import pyarrow.parquet as pq

from retikon_core.config import get_config
from retikon_core.ingestion.pipelines.image import ingest_image
from retikon_core.ingestion.pipelines.metrics import CANONICAL_STAGE_KEYS
from retikon_core.ingestion.types import IngestSource


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


def _assert_stage_timings(metrics: dict[str, object]) -> None:
    stage_timings = metrics.get("stage_timings_ms")
    assert isinstance(stage_timings, dict)
    assert set(stage_timings.keys()) == set(CANONICAL_STAGE_KEYS)
    pipe_ms = metrics.get("pipe_ms")
    assert isinstance(pipe_ms, (int, float))
    assert round(sum(stage_timings.values()), 2) == pipe_ms


def test_image_pipeline_writes_graphar(tmp_path):
    config = get_config()
    fixture = Path("tests/fixtures/sample.jpg")
    source = IngestSource(
        bucket="test-raw",
        name="raw/images/sample.jpg",
        generation="1",
        content_type="image/jpeg",
        size_bytes=fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(fixture),
        uri_scheme="gs",
    )

    result = ingest_image(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    manifest_path = Path(result.manifest_uri)
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["counts"]["ImageAsset"] == 1

    files = [item["uri"] for item in payload.get("files", [])]
    media_uri = next(uri for uri in files if "vertices/MediaAsset/core" in uri)
    image_core_uri = next(uri for uri in files if "vertices/ImageAsset/core" in uri)
    edge_uri = next(uri for uri in files if "edges/DerivedFrom/adj_list" in uri)

    media_table = pq.read_table(media_uri)
    image_table = pq.read_table(image_core_uri)
    edge_table = pq.read_table(edge_uri)

    for value in media_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in image_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in image_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("src_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("dst_id").to_pylist():
        assert _is_uuid4(value)
    assert result.metrics is not None
    _assert_stage_timings(result.metrics)
