import json
import uuid
from pathlib import Path

import pyarrow.parquet as pq

from retikon_core import config as config_module
from retikon_core.config import get_config
from retikon_core.ingestion.ocr import OcrImageResult
from retikon_core.ingestion.pipelines import image as image_pipeline
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
    assert set(image_table.column("embedding_backend").to_pylist()) == {"stub"}
    assert set(image_table.column("embedding_artifact").to_pylist()) == {
        "stub:deterministic"
    }
    assert image_table.column("embedding_model_v2").to_pylist() == [
        "google/siglip2-base-patch16-224"
    ]
    assert set(image_table.column("embedding_backend_v2").to_pylist()) == {"stub"}
    assert set(image_table.column("embedding_artifact_v2").to_pylist()) == {
        "stub:deterministic"
    }
    for value in edge_table.column("src_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("dst_id").to_pylist():
        assert _is_uuid4(value)
    assert result.metrics is not None
    _assert_stage_timings(result.metrics)


def test_image_pipeline_writes_ocr_docchunk(tmp_path, monkeypatch):
    monkeypatch.setenv("OCR_IMAGES", "1")
    monkeypatch.setattr(
        image_pipeline,
        "ocr_result_from_image",
        lambda *_args, **_kwargs: OcrImageResult(
            text="INV-12345",
            conf_avg=91,
            kept_tokens=1,
            raw_tokens=1,
        ),
    )
    config_module.get_config.cache_clear()
    config = get_config()
    fixture = Path("tests/fixtures/sample.jpg")
    source = IngestSource(
        bucket="test-raw",
        name="raw/images/ocr.jpg",
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

    payload = json.loads(Path(result.manifest_uri).read_text(encoding="utf-8"))
    assert payload["counts"]["DocChunk"] == 1
    files = [item["uri"] for item in payload.get("files", [])]
    doc_core_uri = next(uri for uri in files if "vertices/DocChunk/core" in uri)
    doc_text_uri = next(uri for uri in files if "vertices/DocChunk/text" in uri)
    derived_uri = next(uri for uri in files if "edges/DerivedFrom/adj_list" in uri)

    doc_core = pq.read_table(doc_core_uri)
    doc_text = pq.read_table(doc_text_uri)
    derived = pq.read_table(derived_uri)

    assert doc_text.column("content").to_pylist() == ["INV-12345"]
    assert doc_core.column("source_type").to_pylist() == ["image"]
    assert doc_core.column("source_ref_id").to_pylist()[0]
    assert doc_core.column("source_time_ms").to_pylist() == [None]
    assert doc_core.column("ocr_conf_avg").to_pylist() == [91]
    # One image edge + one OCR doc edge.
    assert len(derived) == 2
    config_module.get_config.cache_clear()
