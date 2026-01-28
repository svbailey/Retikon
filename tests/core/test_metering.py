import pyarrow.parquet as pq

from retikon_core.metering import record_usage
from retikon_core.tenancy.types import TenantScope


def test_record_usage_writes_parquet(tmp_path):
    base_uri = tmp_path.as_posix()
    scope = TenantScope(org_id="org-1", site_id="site-1", stream_id="stream-1")
    result = record_usage(
        base_uri=base_uri,
        event_type="query",
        scope=scope,
        api_key_id="key-1",
        modality="text",
        units=1,
        bytes_in=1234,
        pipeline_version="v3.0",
        schema_version="1",
    )
    assert result.rows == 1
    table = pq.read_table(result.uri)
    assert table.column("event_type").to_pylist() == ["query"]
    assert table.column("org_id").to_pylist() == ["org-1"]
    assert table.column("api_key_id").to_pylist() == ["key-1"]
    assert table.column("bytes").to_pylist() == [1234]
