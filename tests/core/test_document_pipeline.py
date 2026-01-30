import json
import uuid
from pathlib import Path

import pyarrow.parquet as pq

from retikon_core.config import get_config
from retikon_core.ingestion.pipelines import document as document_pipeline
from retikon_core.ingestion.types import IngestSource


def _is_uuid4(value: str) -> bool:
    try:
        return uuid.UUID(value).version == 4
    except ValueError:
        return False


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
        uri_scheme="gs",
    )

    result = document_pipeline.ingest_document(
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

    files = [item["uri"] for item in payload.get("files", [])]
    media_uri = next(uri for uri in files if "vertices/MediaAsset/core" in uri)
    chunk_core_uri = next(uri for uri in files if "vertices/DocChunk/core" in uri)
    chunk_text_uri = next(uri for uri in files if "vertices/DocChunk/text" in uri)
    edge_uri = next(uri for uri in files if "edges/DerivedFrom/adj_list" in uri)

    media_table = pq.read_table(media_uri)
    chunk_core_table = pq.read_table(chunk_core_uri)
    chunk_text_table = pq.read_table(chunk_text_uri)
    edge_table = pq.read_table(edge_uri)

    for value in media_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in chunk_core_table.column("id").to_pylist():
        assert _is_uuid4(value)
    for value in chunk_core_table.column("media_asset_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("src_id").to_pylist():
        assert _is_uuid4(value)
    for value in edge_table.column("dst_id").to_pylist():
        assert _is_uuid4(value)

    extracted_text = document_pipeline._extract_text(str(fixture), ".docx")
    core_rows = chunk_core_table.to_pydict()
    text_rows = chunk_text_table.to_pydict()
    assert len(core_rows["id"]) == len(text_rows["content"])
    for idx in range(len(core_rows["id"])):
        char_start = core_rows["char_start"][idx]
        char_end = core_rows["char_end"][idx]
        token_start = core_rows["token_start"][idx]
        token_end = core_rows["token_end"][idx]
        token_count = core_rows["token_count"][idx]
        assert char_end > char_start
        assert token_end > token_start
        assert token_count == token_end - token_start
        assert text_rows["content"][idx] == extracted_text[char_start:char_end]
