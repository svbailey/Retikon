from __future__ import annotations

from pathlib import Path

from retikon_cli import cli


def test_cli_status(monkeypatch, capsys):
    def fake_request(method, url, payload=None, timeout=30, **_kwargs):
        return {"status": "ok", "service": url}

    monkeypatch.setattr(cli, "_request_json", fake_request)
    code = cli.main(
        [
            "status",
            "--ingest-url",
            "http://localhost:8081",
            "--query-url",
            "http://localhost:8082",
        ]
    )
    assert code == 0
    output = capsys.readouterr().out
    assert "ingest" in output
    assert "query" in output


def test_cli_ingest(monkeypatch, capsys):
    captured = {}

    def fake_request(method, url, payload=None, timeout=30, **_kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"status": "completed"}

    monkeypatch.setattr(cli, "_request_json", fake_request)
    code = cli.main(
        [
            "ingest",
            "--path",
            "tests/fixtures/sample.csv",
            "--content-type",
            "text/csv",
            "--ingest-url",
            "http://localhost:8081",
        ]
    )
    assert code == 0
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/ingest")
    assert captured["payload"]["path"].endswith("sample.csv")
    assert captured["payload"]["content_type"] == "text/csv"
    assert "completed" in capsys.readouterr().out


def test_cli_query_metadata(monkeypatch, capsys):
    captured = {}

    def fake_request(method, url, payload=None, timeout=30, **_kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["payload"] = payload
        return {"results": []}

    monkeypatch.setattr(cli, "_request_json", fake_request)
    code = cli.main(
        [
            "query",
            "--search-type",
            "metadata",
            "--metadata",
            "uri=gs://test/doc.pdf",
            "--query-url",
            "http://localhost:8082",
        ]
    )
    assert code == 0
    assert captured["method"] == "POST"
    assert captured["url"].endswith("/query")
    assert captured["payload"]["search_type"] == "metadata"
    assert captured["payload"]["metadata_filters"]["uri"] == "gs://test/doc.pdf"
    assert "results" in capsys.readouterr().out


def test_cli_init_creates_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    example_file = tmp_path / ".env.example"
    example_file.write_text("", encoding="utf-8")

    def fake_build_snapshot(snapshot_uri: str, work_dir):
        Path(snapshot_uri).parent.mkdir(parents=True, exist_ok=True)
        Path(snapshot_uri).write_bytes(b"snapshot")

    monkeypatch.setattr(cli, "_seed_local_graph", lambda _path: None)
    monkeypatch.setattr(cli, "_build_local_snapshot", fake_build_snapshot)

    code = cli.main(
        [
            "init",
            "--env-file",
            str(env_file),
            "--example-file",
            str(example_file),
            "--no-seed",
        ]
    )
    assert code == 0
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert "STORAGE_BACKEND=local" in content


def test_cli_doctor(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    graph_root = tmp_path / "graph"
    snapshot = graph_root / "snapshots" / "retikon.duckdb"
    graph_root.mkdir(parents=True, exist_ok=True)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(b"snapshot")

    env_file.write_text(
        "\n".join(
            [
                "STORAGE_BACKEND=local",
                f"LOCAL_GRAPH_ROOT={graph_root}",
                f"SNAPSHOT_URI={snapshot}",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(cli.shutil, "which", lambda _name: "/usr/bin/true")
    code = cli.main(["doctor", "--env-file", str(env_file)])
    assert code == 0
