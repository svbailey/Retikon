"""Connector registry and shared interfaces."""

from retikon_core.connectors.http import send_webhook_event
from retikon_core.connectors.registry import ConnectorSpec, list_connectors

__all__ = [
    "ConnectorSpec",
    "list_connectors",
    "send_webhook_event",
]
