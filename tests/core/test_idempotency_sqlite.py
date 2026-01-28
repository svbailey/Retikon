from datetime import timedelta
from pathlib import Path

from retikon_core.ingestion.idempotency_sqlite import SqliteIdempotency


def test_sqlite_idempotency_flow(tmp_path: Path) -> None:
    store = SqliteIdempotency(
        path=str(tmp_path / "idem.db"),
        processing_ttl=timedelta(minutes=10),
    )
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 1

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "skip_processing"

    store.mark_completed(decision.doc_id)
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "skip_completed"


def test_sqlite_idempotency_failed_reprocess(tmp_path: Path) -> None:
    store = SqliteIdempotency(
        path=str(tmp_path / "idem.db"),
        processing_ttl=timedelta(minutes=10),
    )
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v3.0",
    )
    store.mark_failed(decision.doc_id, "PERMANENT", "oops")
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v3.0",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 2
