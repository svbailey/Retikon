from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from retikon_core.audit import (
    AuditCompactionPolicy,
    compact_audit_logs,
    record_audit_log,
)


def test_audit_compaction_merges_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDIT_BATCH_SIZE", "1")
    monkeypatch.setenv("AUDIT_BATCH_FLUSH_SECONDS", "0")
    base_uri = tmp_path.as_posix()
    for idx in range(3):
        record_audit_log(
            base_uri=base_uri,
            action=f"test:{idx}",
            decision="allow",
            pipeline_version="v1",
            schema_version="1",
        )

    audit_dir = Path(base_uri) / "vertices" / "AuditLog" / "core"
    before = list(audit_dir.glob("*.parquet"))
    assert len(before) == 3

    policy = AuditCompactionPolicy(
        target_min_bytes=10_000_000,
        target_max_bytes=20_000_000,
        max_files_per_batch=10,
        max_batches=1,
        min_age_seconds=0,
    )
    report = compact_audit_logs(
        base_uri=base_uri,
        policy=policy,
        delete_source=True,
        dry_run=False,
        strict=True,
    )

    after = list(audit_dir.glob("*.parquet"))
    assert report.outputs == 1
    assert len(after) == 1

    table = pq.read_table(after[0])
    assert table.num_rows == 3

    assert report.audit_uri is not None
    assert Path(report.audit_uri).exists()
