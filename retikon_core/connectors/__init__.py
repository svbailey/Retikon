"""Connector registry and shared interfaces."""

from retikon_core.connectors.http import send_webhook_event
from retikon_core.connectors.ocr import (
    OcrConnector,
    load_ocr_connectors,
    register_ocr_connector,
    update_ocr_connector,
)
from retikon_core.connectors.registry import ConnectorSpec, list_connectors

__all__ = [
    "ConnectorSpec",
    "list_connectors",
    "OcrConnector",
    "load_ocr_connectors",
    "register_ocr_connector",
    "update_ocr_connector",
    "send_webhook_event",
]
