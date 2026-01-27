from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.storage.paths import join_uri


@dataclass(frozen=True)
class WebhookDeliveryRecord:
    delivery_id: str
    event_id: str
    webhook_id: str
    attempt: int
    status: str
    status_code: int | None
    error: str | None
    duration_ms: int
    delivered_at: str


def write_webhook_delivery_log(
    *,
    base_uri: str,
    run_id: str,
    records: Iterable[WebhookDeliveryRecord],
) -> str:
    now = datetime.now(timezone.utc).isoformat()
    dest_uri = join_uri(base_uri, "audit", "webhooks", f"{run_id}.jsonl")
    fs, path = fsspec.core.url_to_fs(dest_uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    with fs.open(path, "wb") as handle:
        header = {"run_id": run_id, "written_at": now}
        handle.write((json.dumps(header) + "\n").encode("utf-8"))
        for record in records:
            handle.write((json.dumps(asdict(record)) + "\n").encode("utf-8"))
    return dest_uri
