from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from retikon_core.errors import RecoverableError
from retikon_core.ingestion.idempotency import IdempotencyDecision, build_doc_id


@dataclass(frozen=True)
class SqliteIdempotency:
    path: str
    processing_ttl: timedelta

    def __post_init__(self) -> None:
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=30)

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS idempotency (
                    doc_id TEXT PRIMARY KEY,
                    status TEXT,
                    attempt_count INTEGER,
                    object_generation TEXT,
                    object_size INTEGER,
                    pipeline_version TEXT,
                    started_at INTEGER,
                    updated_at INTEGER,
                    expires_at INTEGER,
                    error_code TEXT,
                    error_message TEXT
                )
                """
            )

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
        now_ts = int(now.timestamp())
        expires_ts = now_ts + int(self.processing_ttl.total_seconds())

        try:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute(
                    "SELECT status, attempt_count, updated_at "
                    "FROM idempotency WHERE doc_id = ?",
                    (doc_id,),
                ).fetchone()

                if row:
                    status, attempt, updated_at = row
                    attempt_count = int(attempt or 0)
                    if status == "COMPLETED":
                        return IdempotencyDecision(
                            action="skip_completed",
                            doc_id=doc_id,
                            status="COMPLETED",
                            attempt_count=attempt_count,
                        )
                    if status == "DLQ":
                        return IdempotencyDecision(
                            action="skip_completed",
                            doc_id=doc_id,
                            status="DLQ",
                            attempt_count=attempt_count,
                        )
                    if status == "PROCESSING" and updated_at:
                        if int(updated_at) >= now_ts - int(
                            self.processing_ttl.total_seconds()
                        ):
                            return IdempotencyDecision(
                                action="skip_processing",
                                doc_id=doc_id,
                                status="PROCESSING",
                                attempt_count=attempt_count,
                            )

                    attempt_count += 1
                    conn.execute(
                        """
                        UPDATE idempotency
                        SET status = ?, attempt_count = ?, object_generation = ?,
                            object_size = ?, pipeline_version = ?, updated_at = ?,
                            expires_at = ?
                        WHERE doc_id = ?
                        """,
                        (
                            "PROCESSING",
                            attempt_count,
                            generation,
                            size,
                            pipeline_version,
                            now_ts,
                            expires_ts,
                            doc_id,
                        ),
                    )
                    return IdempotencyDecision(
                        action="process",
                        doc_id=doc_id,
                        status="PROCESSING",
                        attempt_count=attempt_count,
                    )

                conn.execute(
                    """
                    INSERT INTO idempotency (
                        doc_id, status, attempt_count, object_generation, object_size,
                        pipeline_version, started_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        doc_id,
                        "PROCESSING",
                        1,
                        generation,
                        size,
                        pipeline_version,
                        now_ts,
                        now_ts,
                        expires_ts,
                    ),
                )
                return IdempotencyDecision(
                    action="process",
                    doc_id=doc_id,
                    status="PROCESSING",
                    attempt_count=1,
                )
        except sqlite3.Error as exc:  # pragma: no cover - infrastructure errors
            raise RecoverableError(f"SQLite idempotency failed: {exc}") from exc

    def mark_completed(self, doc_id: str) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        with self._connect() as conn:
            conn.execute(
                "UPDATE idempotency SET status = ?, updated_at = ? WHERE doc_id = ?",
                ("COMPLETED", now_ts, doc_id),
            )

    def mark_failed(self, doc_id: str, error_code: str, error_message: str) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE idempotency
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE doc_id = ?
                """,
                ("FAILED", error_code, error_message, now_ts, doc_id),
            )

    def mark_dlq(self, doc_id: str, error_code: str, error_message: str) -> None:
        now_ts = int(datetime.now(timezone.utc).timestamp())
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE idempotency
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE doc_id = ?
                """,
                ("DLQ", error_code, error_message, now_ts, doc_id),
            )
