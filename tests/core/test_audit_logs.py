from __future__ import annotations

import json
from pathlib import Path

import pyarrow.parquet as pq

from retikon_core.audit import (
    CompactionAuditRecord,
    record_audit_log,
    write_compaction_audit_log,
)
from retikon_core.auth.types import AuthContext
from retikon_core.tenancy.types import TenantScope


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


def test_audit_log_write(tmp_path):
    scope = TenantScope(org_id="org-1", site_id="site-1", stream_id="stream-1")
    auth_context = AuthContext(api_key_id="key-1", scope=scope, is_admin=True)
    result = record_audit_log(
        base_uri=tmp_path.as_posix(),
        action="query:read",
        decision="allow",
        auth_context=auth_context,
        resource="/query",
        request_id="req-1",
        pipeline_version="v1",
        schema_version="1",
    )
    path = Path(result.uri)
    assert path.exists()
    table = pq.read_table(path)
    data = table.to_pydict()
    assert data["action"][0] == "query:read"
    assert data["decision"][0] == "allow"
    assert data["api_key_id"][0] == "key-1"
    assert data["org_id"][0] == "org-1"
