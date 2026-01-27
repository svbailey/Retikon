from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

DEFAULT_INGEST_URL = "http://localhost:8081"
DEFAULT_QUERY_URL = "http://localhost:8082"


def _resolve_ingest_url(value: str | None) -> str:
    return value or os.getenv("RETIKON_INGEST_URL", DEFAULT_INGEST_URL)


def _resolve_query_url(value: str | None) -> str:
    return value or os.getenv("RETIKON_QUERY_URL", DEFAULT_QUERY_URL)


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        detail: str | dict[str, Any] = body
        try:
            detail = json.loads(body)
        except json.JSONDecodeError:
            detail = body or exc.reason
        raise RuntimeError(f"HTTP {exc.code} {detail}") from exc


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _uvicorn_cmd(target: str, host: str, port: int, log_level: str) -> list[str]:
    return [
        "uvicorn",
        target,
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
    ]


def _run_services(
    *,
    ingest_port: int,
    query_port: int,
    host: str,
    log_level: str,
    background: bool,
    dry_run: bool,
) -> int:
    ingest_cmd = _uvicorn_cmd(
        "local_adapter.ingestion_service:app",
        host,
        ingest_port,
        log_level,
    )
    query_cmd = _uvicorn_cmd(
        "local_adapter.query_service:app",
        host,
        query_port,
        log_level,
    )

    if dry_run:
        print(" ".join(ingest_cmd))
        print(" ".join(query_cmd))
        return 0

    ingest_proc = subprocess.Popen(ingest_cmd)
    query_proc = subprocess.Popen(query_cmd)
    procs = [ingest_proc, query_proc]
    if background:
        for proc in procs:
            print(f"Started {proc.args[0]} pid={proc.pid}")
        return 0

    try:
        while True:
            exit_codes = [proc.poll() for proc in procs]
            if any(code is not None for code in exit_codes):
                return next(code for code in exit_codes if code is not None) or 0
            time.sleep(0.5)
    except KeyboardInterrupt:
        for proc in procs:
            proc.terminate()
        for proc in procs:
            proc.wait(timeout=5)
        return 0


def cmd_up(args: argparse.Namespace) -> int:
    return _run_services(
        ingest_port=args.ingest_port,
        query_port=args.query_port,
        host=args.host,
        log_level=args.log_level,
        background=False,
        dry_run=args.dry_run,
    )


def cmd_daemon(args: argparse.Namespace) -> int:
    return _run_services(
        ingest_port=args.ingest_port,
        query_port=args.query_port,
        host=args.host,
        log_level=args.log_level,
        background=True,
        dry_run=args.dry_run,
    )


def cmd_ingest(args: argparse.Namespace) -> int:
    ingest_url = _resolve_ingest_url(args.ingest_url).rstrip("/")
    payload: dict[str, Any] = {"path": args.path}
    if args.content_type:
        payload["content_type"] = args.content_type
    response = _request_json("POST", f"{ingest_url}/ingest", payload=payload)
    _print_json(response)
    return 0


def _parse_metadata(args: argparse.Namespace) -> dict[str, str] | None:
    if args.metadata_json:
        return json.loads(args.metadata_json)
    if not args.metadata:
        return None
    parsed: dict[str, str] = {}
    for item in args.metadata:
        if "=" not in item:
            raise ValueError(f"Invalid metadata filter: {item}")
        key, value = item.split("=", 1)
        parsed[key.strip()] = value.strip()
    return parsed or None


def cmd_query(args: argparse.Namespace) -> int:
    query_url = _resolve_query_url(args.query_url).rstrip("/")
    payload: dict[str, Any] = {"top_k": args.top_k}
    if args.query_text:
        payload["query_text"] = args.query_text
    if args.image_base64:
        payload["image_base64"] = args.image_base64
    if args.mode:
        payload["mode"] = args.mode
    if args.modalities:
        payload["modalities"] = args.modalities
    if args.search_type:
        payload["search_type"] = args.search_type
    metadata_filters = _parse_metadata(args)
    if metadata_filters:
        payload["metadata_filters"] = metadata_filters
    response = _request_json("POST", f"{query_url}/query", payload=payload)
    _print_json(response)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ingest_url = _resolve_ingest_url(args.ingest_url).rstrip("/")
    query_url = _resolve_query_url(args.query_url).rstrip("/")
    ingest_health = _request_json("GET", f"{ingest_url}/health")
    query_health = _request_json("GET", f"{query_url}/health")
    _print_json({"ingest": ingest_health, "query": query_health})
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="retikon")
    subparsers = parser.add_subparsers(dest="command")

    up_parser = subparsers.add_parser("up", help="Run local Retikon services")
    up_parser.add_argument("--host", default="0.0.0.0")
    up_parser.add_argument("--ingest-port", type=int, default=8081)
    up_parser.add_argument("--query-port", type=int, default=8082)
    up_parser.add_argument("--log-level", default="info")
    up_parser.add_argument("--dry-run", action="store_true", help="Print commands only")
    up_parser.set_defaults(func=cmd_up)

    daemon_parser = subparsers.add_parser(
        "daemon", help="Run local services in the background"
    )
    daemon_parser.add_argument("--host", default="0.0.0.0")
    daemon_parser.add_argument("--ingest-port", type=int, default=8081)
    daemon_parser.add_argument("--query-port", type=int, default=8082)
    daemon_parser.add_argument("--log-level", default="info")
    daemon_parser.add_argument(
        "--dry-run", action="store_true", help="Print commands only"
    )
    daemon_parser.set_defaults(func=cmd_daemon)

    ingest_parser = subparsers.add_parser("ingest", help="Ingest a local file")
    ingest_parser.add_argument("--path", required=True)
    ingest_parser.add_argument("--content-type")
    ingest_parser.add_argument("--ingest-url")
    ingest_parser.set_defaults(func=cmd_ingest)

    query_parser = subparsers.add_parser("query", help="Query local snapshot")
    query_parser.add_argument("--text", dest="query_text")
    query_parser.add_argument("--image-base64")
    query_parser.add_argument("--top-k", type=int, default=5)
    query_parser.add_argument("--mode")
    query_parser.add_argument("--modalities", nargs="*")
    query_parser.add_argument(
        "--search-type", choices=["vector", "keyword", "metadata"]
    )
    query_parser.add_argument("--metadata", action="append")
    query_parser.add_argument("--metadata-json")
    query_parser.add_argument("--query-url")
    query_parser.set_defaults(func=cmd_query)

    status_parser = subparsers.add_parser("status", help="Check service health")
    status_parser.add_argument("--ingest-url")
    status_parser.add_argument("--query-url")
    status_parser.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
