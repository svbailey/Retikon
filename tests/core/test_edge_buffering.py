from __future__ import annotations

from retikon_core.edge.buffer import EdgeBuffer


def test_edge_buffer_ttl_prune(tmp_path):
    current = 1000.0

    def now_fn():
        return current

    buf = EdgeBuffer(tmp_path, max_bytes=1024, ttl_seconds=5, now_fn=now_fn)
    buf.add_bytes(b"abc", {"k": "v"})
    current += 10
    buf.prune()
    assert buf.stats().count == 0


def test_edge_buffer_disk_cap(tmp_path):
    buf = EdgeBuffer(tmp_path, max_bytes=5, ttl_seconds=100)
    buf.add_bytes(b"1234", {"idx": 1})
    buf.add_bytes(b"5678", {"idx": 2})
    stats = buf.stats()
    assert stats.count == 1
    assert stats.total_bytes <= 5


def test_edge_buffer_replay(tmp_path):
    buf = EdgeBuffer(tmp_path, max_bytes=1024, ttl_seconds=100)
    buf.add_bytes(b"one", {"idx": 1})
    buf.add_bytes(b"two", {"idx": 2})

    seen = []

    def sender(item):
        seen.append(item.metadata.get("idx"))
        return True

    result = buf.replay(sender)
    assert result["success"] == 2
    assert result["failed"] == 0
    assert buf.stats().count == 0
