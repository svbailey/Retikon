from __future__ import annotations

from pathlib import Path

from retikon_core.edge import agent


def test_edge_agent_scan_and_ingest(tmp_path, monkeypatch):
    file_ok = tmp_path / "sample.txt"
    file_ok.write_text("hello", encoding="utf-8")
    file_skip = tmp_path / "skip.bin"
    file_skip.write_bytes(b"\x00\x01")

    calls: list[dict] = []

    def fake_post(url, payload, timeout=30):
        calls.append({"url": url, "payload": payload})
        return {"status": "ok", "path": payload["path"]}

    monkeypatch.setattr(agent, "_post_json", fake_post)

    results = agent.scan_and_ingest(
        tmp_path,
        "http://localhost:8081/ingest",
        recursive=False,
        allowed_exts=(".txt",),
    )

    assert len(results) == 1
    assert Path(results[0]["path"]).name == "sample.txt"
    assert len(calls) == 1
    assert calls[0]["payload"]["path"].endswith("sample.txt")


def test_guess_content_type():
    path = Path("example.csv")
    assert agent.guess_content_type(path) in {"text/csv", "application/csv", None}
