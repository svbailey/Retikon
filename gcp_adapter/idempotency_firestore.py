from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import storage
import logging

from google.cloud import firestore

from retikon_core.errors import RecoverableError
from retikon_core.ingestion.idempotency import IdempotencyDecision, build_doc_id

_SCOPE_PLACEHOLDER = "-"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FirestoreIdempotency:
    client: firestore.Client
    collection: str
    processing_ttl: timedelta
    completed_ttl: timedelta

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
        doc_ref = self.client.collection(self.collection).document(doc_id)
        now = datetime.now(timezone.utc)
        expires_at = now + self.processing_ttl

        @firestore.transactional
        def _txn(transaction: firestore.Transaction) -> IdempotencyDecision:
            snapshot = doc_ref.get(transaction=transaction)
            if snapshot.exists:
                data = snapshot.to_dict() or {}
                status = data.get("status", "UNKNOWN")
                updated_at = data.get("updated_at")
                attempt = int(data.get("attempt_count", 0))

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

                if status == "PROCESSING":
                    if updated_at and updated_at >= now - self.processing_ttl:
                        return IdempotencyDecision(
                            action="skip_processing",
                            doc_id=doc_id,
                            status="PROCESSING",
                            attempt_count=attempt,
                        )

                attempt += 1
                transaction.update(
                    doc_ref,
                    {
                        "status": "PROCESSING",
                        "attempt_count": attempt,
                        "object_generation": generation,
                        "object_size": size,
                        "pipeline_version": pipeline_version,
                        "updated_at": now,
                        "expires_at": expires_at,
                    },
                )
                return IdempotencyDecision(
                    action="process",
                    doc_id=doc_id,
                    status="PROCESSING",
                    attempt_count=attempt,
                )

            transaction.create(
                doc_ref,
                {
                    "status": "PROCESSING",
                    "attempt_count": 1,
                    "object_generation": generation,
                    "object_size": size,
                    "pipeline_version": pipeline_version,
                    "started_at": now,
                    "updated_at": now,
                    "expires_at": expires_at,
                },
            )
            return IdempotencyDecision(
                action="process",
                doc_id=doc_id,
                status="PROCESSING",
                attempt_count=1,
            )

        try:
            return _txn(self.client.transaction())
        except Exception as exc:  # pragma: no cover - infrastructure errors
            raise RecoverableError(f"Firestore transaction failed: {exc}") from exc

    def mark_completed(self, doc_id: str) -> None:
        now = datetime.now(timezone.utc)
        payload: dict[str, Any] = {
            "status": "COMPLETED",
            "updated_at": now,
        }
        if self.completed_ttl.total_seconds() > 0:
            payload["expires_at"] = now + self.completed_ttl
        else:
            payload["expires_at"] = firestore.DELETE_FIELD
        self.client.collection(self.collection).document(doc_id).update(payload)

    def mark_failed(self, doc_id: str, error_code: str, error_message: str) -> None:
        now = datetime.now(timezone.utc)
        self.client.collection(self.collection).document(doc_id).update(
            {
                "status": "FAILED",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": now,
            }
        )

    def mark_dlq(self, doc_id: str, error_code: str, error_message: str) -> None:
        now = datetime.now(timezone.utc)
        self.client.collection(self.collection).document(doc_id).update(
            {
                "status": "DLQ",
                "error_code": error_code,
                "error_message": error_message,
                "updated_at": now,
            }
        )


def resolve_checksum(md5_hash: str | None, crc32c: str | None) -> str | None:
    if md5_hash:
        return f"md5:{md5_hash}"
    if crc32c:
        return f"crc32c:{crc32c}"
    return None


def resolve_scope_key(
    org_id: str | None,
    site_id: str | None,
    stream_id: str | None,
) -> str:
    return (
        f"{org_id or _SCOPE_PLACEHOLDER}:"
        f"{site_id or _SCOPE_PLACEHOLDER}:"
        f"{stream_id or _SCOPE_PLACEHOLDER}"
    )


def resolve_checksum_scope(checksum: str | None, scope_key: str | None) -> str | None:
    if not checksum:
        return None
    if not scope_key:
        return checksum
    return f"{scope_key}:{checksum}"


def update_object_metadata(
    *,
    client: firestore.Client,
    collection: str,
    doc_id: str,
    bucket: str,
    name: str,
    generation: str,
    checksum: str | None,
    content_type: str | None = None,
    size_bytes: int | None = None,
    duration_ms: int | None = None,
    scope_key: str | None = None,
    scope_org_id: str | None = None,
    scope_site_id: str | None = None,
    scope_stream_id: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "object_bucket": bucket,
        "object_name": name,
        "object_generation": generation,
        "updated_at": datetime.now(timezone.utc),
    }
    if scope_key:
        payload["scope_key"] = scope_key
    if scope_org_id is not None:
        payload["scope_org_id"] = scope_org_id
    if scope_site_id is not None:
        payload["scope_site_id"] = scope_site_id
    if scope_stream_id is not None:
        payload["scope_stream_id"] = scope_stream_id
    if content_type:
        payload["object_content_type"] = content_type
    if size_bytes is not None:
        payload["object_size_bytes"] = size_bytes
    if duration_ms is not None:
        payload["object_duration_ms"] = duration_ms
    resolved_checksum = checksum
    if not resolved_checksum:
        try:
            blob = storage.Client().bucket(bucket).blob(name)
            blob.reload()
            resolved_checksum = resolve_checksum(blob.md5_hash, blob.crc32c)
            if content_type is None and blob.content_type:
                payload["object_content_type"] = blob.content_type
            if size_bytes is None and blob.size is not None:
                payload["object_size_bytes"] = blob.size
        except Exception as exc:
            logger.warning(
                "Failed to hydrate checksum metadata from GCS",
                extra={"bucket": bucket, "name": name, "error_message": str(exc)},
            )
    if resolved_checksum:
        payload["object_checksum"] = resolved_checksum
        checksum_scope = resolve_checksum_scope(resolved_checksum, scope_key)
        if checksum_scope:
            payload["checksum_scope"] = checksum_scope
    # Use merge=True so metadata writes succeed even if the idempotency doc
    # was not created yet (or was removed); this keeps dedupe reliable.
    client.collection(collection).document(doc_id).set(payload, merge=True)


def find_completed_by_checksum(
    *,
    client: firestore.Client,
    collection: str,
    checksum: str,
    scope_key: str | None = None,
    size_bytes: int | None = None,
    content_type: str | None = None,
    duration_ms: int | None = None,
    bucket: str | None = None,
    name: str | None = None,
    limit: int = 5,
) -> dict[str, Any] | None:
    checksum_scope = resolve_checksum_scope(checksum, scope_key)
    if checksum_scope and scope_key:
        query = (
            client.collection(collection)
            .where("checksum_scope", "==", checksum_scope)
            .limit(limit)
        )
    else:
        query = (
            client.collection(collection)
            .where("object_checksum", "==", checksum)
            .limit(limit)
        )
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        if data.get("status") != "COMPLETED":
            continue
        if scope_key and data.get("scope_key") != scope_key:
            continue
        if size_bytes is not None:
            stored_size = data.get("object_size_bytes", data.get("object_size"))
            if stored_size is not None and int(stored_size) != int(size_bytes):
                continue
        if content_type:
            stored_type = data.get("object_content_type")
            if stored_type and stored_type.split(";", 1)[0].strip().lower() != content_type.split(";", 1)[0].strip().lower():
                continue
        if duration_ms is not None:
            stored_duration = data.get("object_duration_ms")
            if stored_duration is not None and int(stored_duration) != int(duration_ms):
                continue
        if bucket is not None and data.get("object_bucket") != bucket:
            continue
        if name is not None and data.get("object_name") != name:
            continue
        data["doc_id"] = snapshot.id
        return data
    return None
