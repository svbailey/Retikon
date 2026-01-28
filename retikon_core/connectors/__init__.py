"""Connector registry and shared interfaces."""

from retikon_core.connectors.http import send_webhook_event

__all__ = [
    "send_webhook_event",
]
