from datetime import timedelta

from retikon_core.ingestion.idempotency import InMemoryIdempotency


def test_idempotency_basic_flow():
    store = InMemoryIdempotency(processing_ttl=timedelta(minutes=10))
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v2.5",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 1

    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v2.5",
    )
    assert decision.action == "skip_processing"

    store.mark_completed(decision.doc_id)
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="1",
        size=123,
        pipeline_version="v2.5",
    )
    assert decision.action == "skip_completed"


def test_idempotency_failed_reprocess():
    store = InMemoryIdempotency(processing_ttl=timedelta(minutes=10))
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v2.5",
    )
    store.mark_failed(decision.doc_id, "PERMANENT", "oops")
    decision = store.begin(
        bucket="bucket",
        name="raw/docs/sample.pdf",
        generation="2",
        size=123,
        pipeline_version="v2.5",
    )
    assert decision.action == "process"
    assert decision.attempt_count == 2
