from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

@dataclass(frozen=True)
class IdempotencyDecision:
    action: str
    doc_id: str
    status: str
    attempt_count: int


def build_doc_id(bucket: str, name: str, generation: str) -> str:
    payload = f"{bucket}/{name}#{generation}".encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    return digest


class InMemoryIdempotency:
    def __init__(self, processing_ttl: timedelta) -> None:
        self.processing_ttl = processing_ttl
        self.store: dict[str, dict[str, Any]] = {}

    def begin(
        self,
        *,
        bucket: str,
        name: str,
        generation: str,
        size: int | None,
        pipeline_version: str,
    ) -> IdempotencyDecision:
        doc_id = build_doc_id(bucket, name, generation)
        now = datetime.now(timezone.utc)
        expires_at = now + self.processing_ttl
        record = self.store.get(doc_id)
        if record:
            status = record.get("status", "UNKNOWN")
            updated_at = record.get("updated_at")
            attempt = int(record.get("attempt_count", 0))
            if status == "COMPLETED":
                return IdempotencyDecision(
                    action="skip_completed",
                    doc_id=doc_id,
                    status="COMPLETED",
                    attempt_count=attempt,
                )
            if status == "DLQ":
                return IdempotencyDecision(
                    action="skip_completed",
                    doc_id=doc_id,
                    status="DLQ",
                    attempt_count=attempt,
                )
            if (
                status == "PROCESSING"
                and updated_at
                and updated_at >= now - self.processing_ttl
            ):
                return IdempotencyDecision(
                    action="skip_processing",
                    doc_id=doc_id,
                    status="PROCESSING",
                    attempt_count=attempt,
                )
            attempt += 1
            started_at = record.get("started_at", now)
        else:
            attempt = 1
            started_at = now

        self.store[doc_id] = {
            "status": "PROCESSING",
            "attempt_count": attempt,
            "object_generation": generation,
            "object_size": size,
            "pipeline_version": pipeline_version,
            "started_at": started_at,
            "updated_at": now,
            "expires_at": expires_at,
        }

        return IdempotencyDecision(
            action="process",
            doc_id=doc_id,
            status="PROCESSING",
            attempt_count=attempt,
        )

    def mark_completed(self, doc_id: str) -> None:
        record = self.store.get(doc_id)
        if record:
            record["status"] = "COMPLETED"
            record["updated_at"] = datetime.now(timezone.utc)

    def mark_failed(self, doc_id: str, error_code: str, error_message: str) -> None:
        record = self.store.get(doc_id)
        if record:
            record["status"] = "FAILED"
            record["error_code"] = error_code
            record["error_message"] = error_message
            record["updated_at"] = datetime.now(timezone.utc)

    def mark_dlq(self, doc_id: str, error_code: str, error_message: str) -> None:
        record = self.store.get(doc_id)
        if record:
            record["status"] = "DLQ"
            record["error_code"] = error_code
            record["error_message"] = error_message
            record["updated_at"] = datetime.now(timezone.utc)
