import json
from pathlib import Path

from retikon_core.config import get_config
from retikon_core.ingestion.pipelines.document import ingest_document
from retikon_core.ingestion.types import IngestSource


def test_document_pipeline_writes_graphar(tmp_path):
    config = get_config()
    fixture = Path("tests/fixtures/sample.docx")
    source = IngestSource(
        bucket="test-raw",
        name="raw/docs/sample.docx",
        generation="1",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        size_bytes=fixture.stat().st_size,
        md5_hash=None,
        crc32c=None,
        local_path=str(fixture),
    )

    result = ingest_document(
        source=source,
        config=config,
        output_uri=tmp_path.as_posix(),
        pipeline_version="v2.5",
        schema_version="1",
    )

    manifest_path = Path(result.manifest_uri)
    assert manifest_path.exists()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["counts"]["MediaAsset"] == 1
    assert payload["counts"]["DocChunk"] >= 1
