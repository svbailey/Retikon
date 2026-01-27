from __future__ import annotations

from retikon_cli import cli


def test_cli_status(monkeypatch, capsys):
    def fake_request(method, url, payload=None, timeout=30):
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

    def fake_request(method, url, payload=None, timeout=30):
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

    def fake_request(method, url, payload=None, timeout=30):
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
