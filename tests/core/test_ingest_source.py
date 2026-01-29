from pathlib import Path

from retikon_core.ingestion.types import IngestSource


def test_ingest_source_default_uri():
    source = IngestSource(
        bucket="demo-bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        content_type="application/pdf",
        size_bytes=123,
        md5_hash=None,
        crc32c=None,
        local_path="tests/fixtures/sample.pdf",
    )
    assert source.uri == "gs://demo-bucket/raw/docs/sample.pdf"


def test_ingest_source_file_uri(tmp_path: Path):
    sample = tmp_path / "sample.txt"
    sample.write_text("ok", encoding="utf-8")
    source = IngestSource(
        bucket="local",
        name="raw/docs/sample.txt",
        generation="local",
        content_type="text/plain",
        size_bytes=2,
        md5_hash=None,
        crc32c=None,
        local_path=str(sample),
        uri_scheme="file",
    )
    assert source.uri == sample.resolve().as_uri()
