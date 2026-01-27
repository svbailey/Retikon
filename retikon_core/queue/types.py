from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol


@dataclass(frozen=True)
class QueueMessage:
    data: bytes
    attributes: dict[str, str]
    message_id: str | None = None


class QueuePublisher(Protocol):
    def publish(
        self,
        *,
        topic: str,
        data: bytes,
        attributes: Mapping[str, str] | None = None,
    ) -> str: ...
