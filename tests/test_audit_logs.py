from __future__ import annotations

import json
from pathlib import Path

from retikon_core.audit import CompactionAuditRecord, write_compaction_audit_log


def test_compaction_audit_log_write(tmp_path):
    record = CompactionAuditRecord(
        run_id="run-1",
        entity_type="DocChunk",
        is_edge=False,
        file_kinds=["core"],
        source_files=[{"uri": "file://input.parquet", "rows": 1}],
        output_files=[{"uri": "file://output.parquet", "rows": 1}],
        rows_in=1,
        rows_out=1,
        bytes_in=100,
        bytes_out=120,
        status="ok",
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:01Z",
    )
    uri = write_compaction_audit_log(
        base_uri=tmp_path.as_posix(),
        run_id="run-1",
        records=[record, record],
    )
    path = Path(uri)
    assert path.exists()
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    header = json.loads(lines[0])
    assert header["run_id"] == "run-1"
