from __future__ import annotations

import re
from typing import Iterable

DEFAULT_PLACEHOLDER = "[REDACTED]"

_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
    re.IGNORECASE,
)
_PHONE_PATTERN = re.compile(
    r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"
)
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CREDIT_CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,16}\b")

_PATTERN_MAP = {
    "email": _EMAIL_PATTERN,
    "phone": _PHONE_PATTERN,
    "ssn": _SSN_PATTERN,
    "credit_card": _CREDIT_CARD_PATTERN,
}

_TYPE_GROUPS = {
    "pii": ("email", "phone", "ssn", "credit_card"),
    "all": ("email", "phone", "ssn", "credit_card"),
}


def _normalize_types(values: Iterable[str] | None) -> tuple[str, ...]:
    if not values:
        return ("pii",)
    cleaned = [str(value).strip().lower() for value in values]
    cleaned = [value for value in cleaned if value]
    return tuple(cleaned) if cleaned else ("pii",)


def _resolve_types(values: Iterable[str] | None) -> tuple[str, ...]:
    normalized = _normalize_types(values)
    resolved: list[str] = []
    for item in normalized:
        if item in _TYPE_GROUPS:
            resolved.extend(_TYPE_GROUPS[item])
        else:
            resolved.append(item)
    deduped: list[str] = []
    for item in resolved:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


def redact_text(
    text: str,
    *,
    redaction_types: Iterable[str] | None = None,
    placeholder: str = DEFAULT_PLACEHOLDER,
) -> str:
    if not text:
        return text
    types = _resolve_types(redaction_types)
    redacted = text
    for item in types:
        pattern = _PATTERN_MAP.get(item)
        if pattern is None:
            continue
        redacted = pattern.sub(placeholder, redacted)
    return redacted
