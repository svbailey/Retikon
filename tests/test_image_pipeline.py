import json
from pathlib import Path

from retikon_core.config import get_config
from retikon_core.ingestion.pipelines.image import ingest_image
from retikon_core.ingestion.types import IngestSource


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
