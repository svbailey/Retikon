import pytest

from retikon_core.errors import RecoverableError
from retikon_core.ingestion import download as download_module


class _FakeReader:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, _size: int) -> bytes:
        self.calls += 1
        if self.calls == 1:
            return b"x" * 1024
        raise OSError("boom")

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return False


class _FakeFS:
    def info(self, _path: str) -> dict:
        return {}

    def open(self, _path: str, _mode: str):
        return _FakeReader()


def test_download_cleanup_on_failure(tmp_path, monkeypatch):
    tmp_file = tmp_path / "download.bin"

    def fake_url_to_fs(_uri: str):
        return _FakeFS(), "ignored"

    monkeypatch.setattr(download_module.fsspec.core, "url_to_fs", fake_url_to_fs)

    class _DummyTmp:
        name = str(tmp_file)

        def close(self) -> None:
            return None

    monkeypatch.setattr(
        download_module.tempfile,
        "NamedTemporaryFile",
        lambda delete=False: _DummyTmp(),
    )

    with pytest.raises(RecoverableError):
        download_module.download_to_tmp("s3://bucket/key", max_bytes=10_000)

    assert not tmp_file.exists()
