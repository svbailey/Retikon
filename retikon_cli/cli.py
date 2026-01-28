from __future__ import annotations

import argparse
import json
import mimetypes
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_INGEST_URL = "http://localhost:8081"
DEFAULT_QUERY_URL = "http://localhost:8082"
DEFAULT_ENV_FILE = ".env"
DEFAULT_ENV_EXAMPLE = ".env.example"

LOCAL_ENV_DEFAULTS: dict[str, str] = {
    "STORAGE_BACKEND": "local",
    "LOCAL_GRAPH_ROOT": "./retikon_data/graph",
    "SNAPSHOT_URI": "./retikon_data/graph/snapshots/retikon.duckdb",
    "ENV": "dev",
    "LOG_LEVEL": "INFO",
    "MAX_RAW_BYTES": "500000000",
    "MAX_VIDEO_SECONDS": "300",
    "MAX_AUDIO_SECONDS": "1200",
    "MAX_FRAMES_PER_VIDEO": "900",
    "CHUNK_TARGET_TOKENS": "512",
    "CHUNK_OVERLAP_TOKENS": "50",
    "GRAPH_PREFIX": "retikon_v2",
    "USE_REAL_MODELS": "0",
}


def _resolve_ingest_url(value: str | None) -> str:
    return value or os.getenv("RETIKON_INGEST_URL", DEFAULT_INGEST_URL)


def _resolve_query_url(value: str | None) -> str:
    return value or os.getenv("RETIKON_QUERY_URL", DEFAULT_QUERY_URL)


def _request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
    api_key_envs: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key_envs:
        for name in api_key_envs:
            value = os.getenv(name)
            if value:
                headers["x-api-key"] = value
                break
        if "x-api-key" not in headers:
            env_path = Path(os.getenv("RETIKON_ENV_FILE", DEFAULT_ENV_FILE))
            env_file = _read_env_file(env_path)
            for name in api_key_envs:
                value = env_file.get(name)
                if value:
                    headers["x-api-key"] = value
                    break
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers=headers,
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


def _read_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip()
    return env


def _append_missing_env(path: Path, missing: dict[str, str]) -> None:
    if not missing:
        return
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n# Added by retikon init\n")
        for key, value in missing.items():
            handle.write(f"{key}={value}\n")


def _apply_env(env: dict[str, str], *, override: bool = False) -> None:
    for key, value in env.items():
        if value == "":
            continue
        if not override and key in os.environ:
            continue
        os.environ[key] = value


def _update_env_file(path: Path, updates: dict[str, str]) -> None:
    if not updates:
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    updated_lines: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            updated_lines.append(raw)
            continue
        key, _value = raw.split("=", 1)
        key = key.strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            updated_lines.append(raw)
    for key, value in updates.items():
        if key not in seen:
            updated_lines.append(f"{key}={value}")
    path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _ensure_env_file(env_path: Path, example_path: Path) -> dict[str, str]:
    if not env_path.exists():
        if example_path.exists():
            shutil.copy2(example_path, env_path)
            print(f"Created {env_path} from {example_path}")
        else:
            env_path.write_text("", encoding="utf-8")
            print(f"Created empty {env_path}")
    env = _read_env_file(env_path)
    missing = {
        key: value for key, value in LOCAL_ENV_DEFAULTS.items() if key not in env
    }
    _append_missing_env(env_path, missing)
    env.update(missing)
    return env


def _infer_modality(extension: str, config) -> str:
    if extension in config.allowed_doc_ext:
        return "document"
    if extension in config.allowed_image_ext:
        return "image"
    if extension in config.allowed_audio_ext:
        return "audio"
    if extension in config.allowed_video_ext:
        return "video"
    raise RuntimeError(f"Unsupported extension: {extension}")


def _prefix_for_modality(modality: str) -> str:
    if modality == "document":
        return "docs"
    if modality == "image":
        return "images"
    if modality == "audio":
        return "audio"
    if modality == "video":
        return "videos"
    raise RuntimeError(f"Unsupported modality: {modality}")


def _seed_local_graph(sample_path: Path) -> None:
    from retikon_core.config import get_config
    from retikon_core.ingestion.eventarc import GcsEvent
    from retikon_core.ingestion.router import (
        _check_size,
        _ensure_allowed,
        _run_pipeline,
        _schema_version,
        pipeline_version,
    )
    from retikon_core.ingestion.types import IngestSource

    os.environ.setdefault("RETIKON_TOKENIZER", "stub")

    config = get_config()
    extension = sample_path.suffix.lower()
    if not extension:
        raise RuntimeError("Sample file has no extension")
    content_type = mimetypes.guess_type(sample_path.as_posix())[0]
    modality = _infer_modality(extension, config)
    object_name = f"raw/{_prefix_for_modality(modality)}/{sample_path.name}"

    event = GcsEvent(
        bucket=config.raw_bucket or "local",
        name=object_name,
        generation="local",
        content_type=content_type,
        size=sample_path.stat().st_size,
        md5_hash=None,
        crc32c=None,
    )

    _check_size(event, config)
    _ensure_allowed(event, config, modality)

    source = IngestSource(
        bucket=event.bucket,
        name=event.name,
        generation=event.generation,
        content_type=event.content_type,
        size_bytes=event.size,
        md5_hash=None,
        crc32c=None,
        local_path=str(sample_path),
    )

    _run_pipeline(
        modality=modality,
        source=source,
        config=config,
        output_uri=config.graph_root_uri(),
        pipeline_version_value=pipeline_version(),
        schema_version=_schema_version(),
    )


def _build_local_snapshot(snapshot_uri: str, work_dir: Path) -> None:
    from retikon_core.config import get_config
    from retikon_core.query_engine.index_builder import build_snapshot

    config = get_config()
    build_snapshot(
        graph_uri=config.graph_root_uri(),
        snapshot_uri=snapshot_uri,
        work_dir=str(work_dir),
        copy_local=False,
        fallback_local=False,
        allow_install=False,
    )


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
    response = _request_json(
        "POST",
        f"{ingest_url}/ingest",
        payload=payload,
        api_key_envs=("INGEST_API_KEY", "QUERY_API_KEY"),
    )
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
    response = _request_json(
        "POST",
        f"{query_url}/query",
        payload=payload,
        api_key_envs=("QUERY_API_KEY",),
    )
    _print_json(response)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    ingest_url = _resolve_ingest_url(args.ingest_url).rstrip("/")
    query_url = _resolve_query_url(args.query_url).rstrip("/")
    ingest_health = _request_json("GET", f"{ingest_url}/health")
    query_health = _request_json("GET", f"{query_url}/health")
    _print_json({"ingest": ingest_health, "query": query_health})
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    example_path = Path(args.example_file)
    env = _ensure_env_file(env_path, example_path)
    _apply_env(env, override=False)

    storage_backend = os.getenv("STORAGE_BACKEND", "local")
    if storage_backend != "local":
        print("STORAGE_BACKEND is not local; skipping local bootstrap.")
        return 0

    local_graph_root = os.getenv(
        "LOCAL_GRAPH_ROOT", LOCAL_ENV_DEFAULTS["LOCAL_GRAPH_ROOT"]
    )
    snapshot_uri = os.getenv("SNAPSHOT_URI", LOCAL_ENV_DEFAULTS["SNAPSHOT_URI"])
    overrides: dict[str, str] = {}
    if not local_graph_root:
        local_graph_root = LOCAL_ENV_DEFAULTS["LOCAL_GRAPH_ROOT"]
        overrides["LOCAL_GRAPH_ROOT"] = local_graph_root
    if not snapshot_uri or snapshot_uri.startswith("gs://"):
        snapshot_uri = f"{local_graph_root}/snapshots/retikon.duckdb"
        overrides["SNAPSHOT_URI"] = snapshot_uri
    if overrides:
        _update_env_file(env_path, overrides)
        env.update(overrides)
        _apply_env(overrides, override=True)
    os.environ["LOCAL_GRAPH_ROOT"] = local_graph_root
    os.environ["SNAPSHOT_URI"] = snapshot_uri

    graph_root_path = Path(local_graph_root)
    snapshot_path = Path(snapshot_uri)
    graph_root_path.mkdir(parents=True, exist_ok=True)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)

    if args.seed:
        sample_path = Path(args.seed_file)
        if not sample_path.exists():
            raise RuntimeError(f"Seed file not found: {sample_path}")
        from retikon_core.config import get_config

        get_config.cache_clear()
        _seed_local_graph(sample_path)

    if not snapshot_path.exists() or args.force_snapshot:
        from retikon_core.config import get_config

        get_config.cache_clear()
        work_dir = graph_root_path / ".retikon_tmp"
        work_dir.mkdir(parents=True, exist_ok=True)
        _build_local_snapshot(str(snapshot_path), work_dir)

    print("Local bootstrap complete.")
    print(f"- ENV file: {env_path}")
    print(f"- Graph root: {graph_root_path}")
    print(f"- Snapshot: {snapshot_path}")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    env_path = Path(args.env_file)
    env = _read_env_file(env_path)
    if env:
        _apply_env(env)

    checks: list[tuple[str, bool, str]] = []

    def check_bin(name: str) -> None:
        available = shutil.which(name) is not None
        msg = "ok" if available else "missing"
        checks.append((name, available, msg))

    check_bin("ffmpeg")
    check_bin("ffprobe")
    check_bin("pdftoppm")

    storage_backend = os.getenv("STORAGE_BACKEND", "local")
    checks.append(("STORAGE_BACKEND", storage_backend == "local", storage_backend))

    local_graph_root = os.getenv("LOCAL_GRAPH_ROOT")
    if local_graph_root:
        exists = Path(local_graph_root).exists()
        checks.append(("LOCAL_GRAPH_ROOT", exists, local_graph_root))
    else:
        checks.append(("LOCAL_GRAPH_ROOT", False, "unset"))

    snapshot_uri = os.getenv("SNAPSHOT_URI")
    if snapshot_uri:
        exists = Path(snapshot_uri).exists()
        checks.append(("SNAPSHOT_URI", exists, snapshot_uri))
    else:
        checks.append(("SNAPSHOT_URI", False, "unset"))

    ok = True
    for name, passed, info in checks:
        status = "ok" if passed else "missing"
        if not passed:
            ok = False
        print(f"{name}: {status} ({info})")

    return 0 if ok else 1


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

    init_parser = subparsers.add_parser("init", help="Bootstrap local Core setup")
    init_parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    init_parser.add_argument("--example-file", default=DEFAULT_ENV_EXAMPLE)
    init_parser.add_argument(
        "--seed",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    init_parser.add_argument("--seed-file", default="tests/fixtures/sample.csv")
    init_parser.add_argument("--force-snapshot", action="store_true")
    init_parser.set_defaults(func=cmd_init)

    doctor_parser = subparsers.add_parser("doctor", help="Check local prerequisites")
    doctor_parser.add_argument("--env-file", default=DEFAULT_ENV_FILE)
    doctor_parser.set_defaults(func=cmd_doctor)

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
