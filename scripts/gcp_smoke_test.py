from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from google.cloud import firestore

from retikon_core.ingestion.idempotency import build_doc_id

DEFAULT_PROJECT = "simitor"
DEFAULT_REGION = "us-central1"
DEFAULT_RAW_BUCKET = "retikon-raw-simitor-dev"
DEFAULT_GRAPH_BUCKET = "retikon-graph-simitor-dev"
DEFAULT_GRAPH_PREFIX = "retikon_v2"
DEFAULT_QUERY_URL = "https://retikon-query-dev-yt27ougp4q-uc.a.run.app/query"
DEFAULT_DLQ_TOPIC = "retikon-ingest-dlq"


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _run_json(cmd: list[str]) -> dict:
    return json.loads(_run(cmd))


@dataclass(frozen=True)
class SmokeContext:
    project: str
    region: str
    raw_bucket: str
    graph_bucket: str
    graph_prefix: str
    query_url: str
    auth_token: str
    keep: bool
    dlq_topic: str
    start_time: float
    object_name: str
    raw_uri: str


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _upload_sample(bucket: str, object_name: str) -> None:
    source = Path("tests/fixtures/sample.csv")
    _run(["gcloud", "storage", "cp", str(source), f"gs://{bucket}/{object_name}"])


def _object_meta(bucket: str, object_name: str) -> dict:
    return _run_json(
        [
            "gcloud",
            "storage",
            "objects",
            "describe",
            f"gs://{bucket}/{object_name}",
            "--format=json",
        ]
    )


def _query(query_url: str, auth_token: str) -> tuple[dict, int]:
    payload = json.dumps({"query_text": "retikon smoke", "top_k": 3}).encode("utf-8")
    start = time.monotonic()
    req = subprocess.Popen(
        [
            "curl",
            "-s",
            "-X",
            "POST",
            query_url,
            "-H",
            f"Authorization: Bearer {auth_token}",
            "-H",
            "Content-Type: application/json",
            "-d",
            payload.decode("utf-8"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out, err = req.communicate(timeout=60)
    latency_ms = int((time.monotonic() - start) * 1000)
    if req.returncode != 0:
        raise RuntimeError(f"Query failed: {err.strip()}")
    return json.loads(out or "{}"), latency_ms


def _wait_firestore_status(
    client: firestore.Client,
    collection: str,
    doc_id: str,
    timeout_s: int = 120,
) -> tuple[str | None, dict | None]:
    deadline = time.time() + timeout_s
    status = None
    data = None
    while time.time() < deadline:
        snap = client.collection(collection).document(doc_id).get()
        if snap.exists:
            data = snap.to_dict() or {}
            status = data.get("status")
            if status in {"COMPLETED", "FAILED", "DLQ"}:
                return status, data
        time.sleep(2)
    return status, data


def _read_manifest(manifest_uri: str) -> dict:
    raw = _run(["gcloud", "storage", "cat", manifest_uri])
    return json.loads(raw)


def _delete_object(uri: str) -> None:
    _run(["gcloud", "storage", "rm", uri])


def _delete_manifest_outputs(manifest: dict) -> list[str]:
    removed: list[str] = []
    if "files" in manifest:
        for item in manifest.get("files", []):
            uri = item.get("uri")
            if uri:
                _delete_object(uri)
                removed.append(uri)
        return removed
    for section in ("vertices", "edges"):
        for item in manifest.get(section, []):
            uri = item.get("uri")
            if uri:
                _delete_object(uri)
                removed.append(uri)
    return removed


def _publish_dlq(ctx: SmokeContext) -> str:
    payload = json.dumps(
        {
            "error_code": "SMOKE",
            "error_message": "tier3 smoke test",
            "attempt_count": 1,
            "modality": "document",
            "gcs_event": {
                "bucket": ctx.raw_bucket,
                "name": ctx.object_name,
                "generation": "1",
                "content_type": "text/csv",
                "size": 18,
            },
            "cloudevent": {"id": f"tier3-{int(ctx.start_time)}"},
        }
    )
    output = _run(
        [
            "gcloud",
            "pubsub",
            "topics",
            "publish",
            ctx.dlq_topic,
            "--project",
            ctx.project,
            "--message",
            payload,
            "--format=json",
        ]
    )
    data = json.loads(output or "{}")
    message_ids = data.get("messageIds") or []
    if message_ids:
        return str(message_ids[0])
    return ""


def main() -> int:
    project = _env("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT)
    region = _env("GOOGLE_CLOUD_REGION", DEFAULT_REGION)
    raw_bucket = _env("RAW_BUCKET", DEFAULT_RAW_BUCKET)
    graph_bucket = _env("GRAPH_BUCKET", DEFAULT_GRAPH_BUCKET)
    graph_prefix = _env("GRAPH_PREFIX", DEFAULT_GRAPH_PREFIX)
    query_url = _env("QUERY_URL", DEFAULT_QUERY_URL)
    auth_token = os.getenv("RETIKON_AUTH_TOKEN") or os.getenv("RETIKON_JWT")
    keep = os.getenv("KEEP_SMOKE_ARTIFACTS", "0") == "1"
    dlq_topic = _env("DLQ_TOPIC", DEFAULT_DLQ_TOPIC)
    if not auth_token:
        raise SystemExit("RETIKON_AUTH_TOKEN is required for query validation")

    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    object_name = f"raw/docs/tier3-{stamp}.csv"
    ctx = SmokeContext(
        project=project,
        region=region,
        raw_bucket=raw_bucket,
        graph_bucket=graph_bucket,
        graph_prefix=graph_prefix,
        query_url=query_url,
        auth_token=auth_token,
        keep=keep,
        dlq_topic=dlq_topic,
        start_time=time.time(),
        object_name=object_name,
        raw_uri=f"gs://{raw_bucket}/{object_name}",
    )

    print(f"Project: {ctx.project} Region: {ctx.region}")
    print(f"Uploading: {ctx.raw_uri}")
    _upload_sample(ctx.raw_bucket, ctx.object_name)

    meta = _object_meta(ctx.raw_bucket, ctx.object_name)
    generation = str(meta.get("generation"))

    doc_id = build_doc_id(ctx.raw_bucket, ctx.object_name, generation)
    client = firestore.Client(project=ctx.project)
    collection = os.getenv("FIRESTORE_COLLECTION", "ingestion_events")

    status, data = _wait_firestore_status(client, collection, doc_id)

    manifest_uri = None
    if data:
        manifest_uri = data.get("manifest_uri")

    query_result, query_latency_ms = _query(ctx.query_url, ctx.auth_token)
    dlq_message_id = _publish_dlq(ctx)

    summary = {
        "raw_object": ctx.raw_uri,
        "firestore_doc_id": doc_id,
        "firestore_status": status,
        "manifest_uri": manifest_uri,
        "query_url": ctx.query_url,
        "query_results": len(query_result.get("results", [])),
        "query_latency_ms": query_latency_ms,
        "dlq_message_id": dlq_message_id,
    }

    print(json.dumps(summary, indent=2))

    if keep:
        return 0

    removed = []
    if manifest_uri:
        try:
            manifest = _read_manifest(manifest_uri)
            removed.extend(_delete_manifest_outputs(manifest))
            _delete_object(manifest_uri)
        except Exception as exc:
            print(f"Cleanup warning: {exc}")
    _delete_object(ctx.raw_uri)

    print(f"Removed graph objects: {len(removed)}")
    for uri in removed:
        print(f"- {uri}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
