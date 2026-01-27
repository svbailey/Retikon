from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


@dataclass(frozen=True)
class BufferItem:
    item_id: str
    created_at: float
    size_bytes: int
    payload_path: str
    metadata: dict[str, Any]

    def read_bytes(self) -> bytes:
        return Path(self.payload_path).read_bytes()


@dataclass(frozen=True)
class BufferStats:
    count: int
    total_bytes: int
    oldest_age_s: float | None
    newest_age_s: float | None


class EdgeBuffer:
    def __init__(
        self,
        base_dir: str | Path,
        max_bytes: int,
        ttl_seconds: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self.base_dir = Path(base_dir)
        self.payload_dir = self.base_dir / "payloads"
        self.meta_dir = self.base_dir / "meta"
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self._now = now_fn or time.time
        self.payload_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

    def add_bytes(self, payload: bytes, metadata: dict[str, Any]) -> BufferItem:
        item_id = str(uuid.uuid4())
        created_at = self._now()
        payload_path = self.payload_dir / f"{item_id}.bin"
        meta_path = self.meta_dir / f"{item_id}.json"

        _atomic_write_bytes(payload_path, payload)
        meta_payload = {
            "item_id": item_id,
            "created_at": created_at,
            "size_bytes": len(payload),
            "payload_path": str(payload_path),
            "metadata": metadata,
        }
        _atomic_write_json(meta_path, meta_payload)

        self.prune()
        return BufferItem(
            item_id=item_id,
            created_at=created_at,
            size_bytes=len(payload),
            payload_path=str(payload_path),
            metadata=metadata,
        )

    def list_items(self) -> list[BufferItem]:
        items: list[BufferItem] = []
        for meta_path in sorted(self.meta_dir.glob("*.json")):
            try:
                data = json.loads(meta_path.read_text(encoding="utf-8"))
                payload_path = Path(data["payload_path"])
                if not payload_path.exists():
                    meta_path.unlink(missing_ok=True)
                    continue
                items.append(
                    BufferItem(
                        item_id=data["item_id"],
                        created_at=float(data["created_at"]),
                        size_bytes=int(data["size_bytes"]),
                        payload_path=str(payload_path),
                        metadata=dict(data.get("metadata", {})),
                    )
                )
            except (ValueError, KeyError):
                meta_path.unlink(missing_ok=True)
        return items

    def stats(self) -> BufferStats:
        items = self.list_items()
        if not items:
            return BufferStats(
                count=0,
                total_bytes=0,
                oldest_age_s=None,
                newest_age_s=None,
            )
        now = self._now()
        total_bytes = sum(item.size_bytes for item in items)
        created_times = sorted(item.created_at for item in items)
        oldest_age = now - created_times[0]
        newest_age = now - created_times[-1]
        return BufferStats(
            count=len(items),
            total_bytes=total_bytes,
            oldest_age_s=round(oldest_age, 2),
            newest_age_s=round(newest_age, 2),
        )

    def prune(self) -> None:
        items = self.list_items()
        if not items:
            return
        now = self._now()
        for item in items:
            if now - item.created_at > self.ttl_seconds:
                self._remove_item(item)

        items = self.list_items()
        total = sum(item.size_bytes for item in items)
        if total <= self.max_bytes:
            return
        for item in sorted(items, key=lambda x: x.created_at):
            self._remove_item(item)
            total -= item.size_bytes
            if total <= self.max_bytes:
                break

    def replay(self, sender: Callable[[BufferItem], bool]) -> dict[str, int]:
        success = 0
        failed = 0
        for item in sorted(self.list_items(), key=lambda x: x.created_at):
            try:
                ok = sender(item)
            except Exception:
                ok = False
            if ok:
                self._remove_item(item)
                success += 1
            else:
                failed += 1
                break
        return {"success": success, "failed": failed}

    def _remove_item(self, item: BufferItem) -> None:
        try:
            os.remove(item.payload_path)
        except FileNotFoundError:
            pass
        meta_path = self.meta_dir / f"{item.item_id}.json"
        meta_path.unlink(missing_ok=True)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    tmp_path = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_bytes(payload)
    os.replace(tmp_path, path)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    tmp_path = path.with_suffix(".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp_path, path)
