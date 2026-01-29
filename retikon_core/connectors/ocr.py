from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable
from urllib.parse import urlparse

import fsspec

from retikon_core.storage.paths import join_uri

_ALLOWED_AUTH_TYPES: tuple[str, ...] = ("none", "header", "bearer")


@dataclass(frozen=True)
class OcrConnector:
    id: str
    name: str
    url: str
    auth_type: str
    auth_header: str | None
    token_env: str | None
    enabled: bool
    is_default: bool
    max_pages: int | None
    timeout_s: float | None
    notes: str | None
    created_at: str
    updated_at: str


def ocr_connectors_uri(base_uri: str) -> str:
    return join_uri(base_uri, "control", "ocr_connectors.json")


def load_ocr_connectors(base_uri: str) -> list[OcrConnector]:
    uri = ocr_connectors_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("connectors", []) if isinstance(payload, dict) else []
    results: list[OcrConnector] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(_connector_from_dict(item))
    return results


def save_ocr_connectors(
    base_uri: str,
    connectors: Iterable[OcrConnector],
) -> str:
    uri = ocr_connectors_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "connectors": [asdict(connector) for connector in connectors],
    }
    with fs.open(path, "wb") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
    return uri


def register_ocr_connector(
    *,
    base_uri: str,
    name: str,
    url: str,
    auth_type: str = "none",
    auth_header: str | None = None,
    token_env: str | None = None,
    enabled: bool = True,
    is_default: bool = False,
    max_pages: int | None = None,
    timeout_s: float | None = None,
    notes: str | None = None,
) -> OcrConnector:
    now = datetime.now(timezone.utc).isoformat()
    connector = OcrConnector(
        id=str(uuid.uuid4()),
        name=name,
        url=url,
        auth_type=_normalize_auth_type(auth_type),
        auth_header=_normalize_optional_str(auth_header),
        token_env=_normalize_optional_str(token_env),
        enabled=enabled,
        is_default=is_default,
        max_pages=max_pages,
        timeout_s=timeout_s,
        notes=_normalize_optional_str(notes),
        created_at=now,
        updated_at=now,
    )
    _validate_connector(connector)
    connectors = load_ocr_connectors(base_uri)
    if connector.is_default:
        connectors = [
            existing if not existing.is_default else _unset_default(existing)
            for existing in connectors
        ]
    connectors.append(connector)
    save_ocr_connectors(base_uri, connectors)
    return connector


def update_ocr_connector(
    *,
    base_uri: str,
    connector: OcrConnector,
) -> OcrConnector:
    _validate_connector(connector)
    connectors = load_ocr_connectors(base_uri)
    updated: list[OcrConnector] = []
    for existing in connectors:
        if existing.id == connector.id:
            updated.append(connector)
        else:
            updated.append(existing)
    if connector.is_default:
        updated = [
            item if item.id == connector.id else _unset_default(item)
            for item in updated
        ]
    save_ocr_connectors(base_uri, updated)
    return connector


def _normalize_auth_type(value: str | None) -> str:
    raw = (value or "none").strip().lower()
    return raw or "none"


def _normalize_optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _unset_default(connector: OcrConnector) -> OcrConnector:
    if not connector.is_default:
        return connector
    return OcrConnector(
        id=connector.id,
        name=connector.name,
        url=connector.url,
        auth_type=connector.auth_type,
        auth_header=connector.auth_header,
        token_env=connector.token_env,
        enabled=connector.enabled,
        is_default=False,
        max_pages=connector.max_pages,
        timeout_s=connector.timeout_s,
        notes=connector.notes,
        created_at=connector.created_at,
        updated_at=connector.updated_at,
    )


def _validate_connector(connector: OcrConnector) -> None:
    if not connector.name.strip():
        raise ValueError("OCR connector name is required")
    parsed = urlparse(connector.url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("OCR connector url must be http(s)")
    if connector.auth_type not in _ALLOWED_AUTH_TYPES:
        raise ValueError(
            f"OCR connector auth_type must be one of: {', '.join(_ALLOWED_AUTH_TYPES)}"
        )
    if connector.auth_type == "header":
        if not connector.auth_header:
            raise ValueError("auth_header is required when auth_type=header")
        if not connector.token_env:
            raise ValueError("token_env is required when auth_type=header")
    if connector.auth_type == "bearer" and not connector.token_env:
        raise ValueError("token_env is required when auth_type=bearer")
    if connector.max_pages is not None and connector.max_pages < 0:
        raise ValueError("max_pages must be >= 0")
    if connector.timeout_s is not None and connector.timeout_s <= 0:
        raise ValueError("timeout_s must be > 0")


def _connector_from_dict(payload: dict[str, object]) -> OcrConnector:
    return OcrConnector(
        id=str(payload.get("id", "")),
        name=str(payload.get("name", "")),
        url=str(payload.get("url", "")),
        auth_type=_normalize_auth_type(str(payload.get("auth_type", "none"))),
        auth_header=_normalize_optional_str(payload.get("auth_header") or None),
        token_env=_normalize_optional_str(payload.get("token_env") or None),
        enabled=bool(payload.get("enabled", True)),
        is_default=bool(payload.get("is_default", False)),
        max_pages=_coerce_int(payload.get("max_pages")),
        timeout_s=_coerce_float(payload.get("timeout_s")),
        notes=_normalize_optional_str(payload.get("notes") or None),
        created_at=str(payload.get("created_at", "")),
        updated_at=str(payload.get("updated_at", "")),
    )


def _coerce_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
