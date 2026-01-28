from pathlib import Path

from retikon_core.query_engine.snapshot import download_snapshot


def test_download_snapshot_local(tmp_path: Path) -> None:
    snapshot_path = tmp_path / "sample.duckdb"
    snapshot_path.write_bytes(b"snapshot-data")
    sidecar_path = tmp_path / "sample.duckdb.json"
    sidecar_path.write_text('{"source": "local"}', encoding="utf-8")

    dest_dir = tmp_path / "out"
    info = download_snapshot(str(snapshot_path), dest_dir=str(dest_dir))

    local_path = Path(info.local_path)
    assert local_path.exists()
    assert local_path.read_bytes() == b"snapshot-data"
    assert info.metadata == {"source": "local"}
