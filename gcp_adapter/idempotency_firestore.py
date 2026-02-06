from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from google.cloud import firestore

from retikon_core.errors import RecoverableError
from retikon_core.ingestion.idempotency import IdempotencyDecision, build_doc_id


@dataclass(frozen=True)
class FirestoreIdempotency:
    client: firestore.Client
    collection: str
    processing_ttl: timedelta

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
        self.client.collection(self.collection).document(doc_id).update(
            {
                "status": "COMPLETED",
                "updated_at": now,
            }
        )

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


def update_object_metadata(
    *,
    client: firestore.Client,
    collection: str,
    doc_id: str,
    bucket: str,
    name: str,
    generation: str,
    checksum: str | None,
) -> None:
    payload: dict[str, Any] = {
        "object_bucket": bucket,
        "object_name": name,
        "object_generation": generation,
        "updated_at": datetime.now(timezone.utc),
    }
    if checksum:
        payload["object_checksum"] = checksum
    client.collection(collection).document(doc_id).update(payload)


def find_completed_by_checksum(
    *,
    client: firestore.Client,
    collection: str,
    checksum: str,
    bucket: str | None = None,
    name: str | None = None,
    limit: int = 5,
) -> dict[str, Any] | None:
    query = (
        client.collection(collection)
        .where("object_checksum", "==", checksum)
        .limit(limit)
    )
    for snapshot in query.stream():
        data = snapshot.to_dict() or {}
        if data.get("status") != "COMPLETED":
            continue
        if bucket is not None and data.get("object_bucket") != bucket:
            continue
        if name is not None and data.get("object_name") != name:
            continue
        data["doc_id"] = snapshot.id
        return data
    return None
