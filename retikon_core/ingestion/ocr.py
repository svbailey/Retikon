from __future__ import annotations

import base64
import json
import os
import shutil
import urllib.error
import urllib.request

import fitz
from PIL import Image

from retikon_core.connectors.ocr import load_ocr_connectors
from retikon_core.errors import PermanentError, RecoverableError


def _load_pytesseract():
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError as exc:
        raise PermanentError(
            "OCR enabled but pytesseract is not installed."
        ) from exc
    if shutil.which("tesseract") is None:
        raise PermanentError("OCR enabled but tesseract binary is missing.")
    return pytesseract


def ocr_text_from_image(image: Image.Image) -> str:
    pytesseract = _load_pytesseract()
    return (pytesseract.image_to_string(image) or "").strip()


def ocr_text_from_pdf(
    path: str,
    max_pages: int,
    base_uri: str | None = None,
) -> str:
    connector = _select_ocr_connector(base_uri)
    if connector is not None:
        return _ocr_text_from_pdf_via_connector(path, connector, max_pages)
    return _ocr_text_from_pdf_local(path, max_pages)


def _ocr_text_from_pdf_local(path: str, max_pages: int) -> str:
    pytesseract = _load_pytesseract()
    doc = fitz.open(path)
    texts: list[str] = []
    try:
        total_pages = len(doc)
        limit = total_pages if max_pages <= 0 else min(total_pages, max_pages)
        for page_index in range(limit):
            page = doc.load_page(page_index)
            pix = page.get_pixmap()
            mode = "RGBA" if pix.alpha else "RGB"
            image = Image.frombytes(mode, (pix.width, pix.height), pix.samples)
            if mode == "RGBA":
                image = image.convert("RGB")
            text = (pytesseract.image_to_string(image) or "").strip()
            if text:
                texts.append(text)
    finally:
        doc.close()
    return "\n".join(texts).strip()


def _select_ocr_connector(base_uri: str | None):
    if not base_uri:
        return None
    connectors = [item for item in load_ocr_connectors(base_uri) if item.enabled]
    if not connectors:
        return None
    requested = os.getenv("OCR_CONNECTOR_ID")
    if requested:
        for connector in connectors:
            if connector.id == requested:
                return connector
        raise PermanentError(f"OCR connector not found: {requested}")
    defaults = [item for item in connectors if item.is_default]
    if len(defaults) == 1:
        return defaults[0]
    if len(defaults) > 1:
        raise PermanentError("Multiple default OCR connectors configured")
    if len(connectors) == 1:
        return connectors[0]
    raise PermanentError("Multiple OCR connectors enabled; set OCR_CONNECTOR_ID")


def _ocr_text_from_pdf_via_connector(path: str, connector, max_pages: int) -> str:
    with open(path, "rb") as handle:
        payload_bytes = handle.read()
    payload = {
        "content_base64": base64.b64encode(payload_bytes).decode("ascii"),
        "content_type": "application/pdf",
        "max_pages": max_pages,
    }
    headers = _connector_headers(connector)
    request = urllib.request.Request(
        connector.url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    timeout = connector.timeout_s or 30
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        message = _read_error_body(exc)
        if 400 <= exc.code < 500:
            raise PermanentError(
                f"OCR connector returned {exc.code}: {message}"
            ) from exc
        raise RecoverableError(
            f"OCR connector returned {exc.code}: {message}"
        ) from exc
    except urllib.error.URLError as exc:
        raise RecoverableError(f"OCR connector request failed: {exc}") from exc

    try:
        payload = json.loads(body) if body else {}
    except json.JSONDecodeError as exc:
        raise PermanentError("OCR connector returned invalid JSON") from exc
    text = payload.get("text")
    if not isinstance(text, str):
        raise PermanentError("OCR connector response missing text")
    return text.strip()


def _connector_headers(connector) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    auth_type = connector.auth_type
    if auth_type == "none":
        return headers
    token_env = connector.token_env or ""
    token = os.getenv(token_env)
    if not token:
        raise PermanentError(f"OCR connector token env missing: {token_env}")
    if auth_type == "bearer":
        headers["Authorization"] = f"Bearer {token}"
        return headers
    if auth_type == "header":
        header = connector.auth_header or ""
        if not header:
            raise PermanentError("OCR connector auth_header is required")
        headers[header] = token
        return headers
    raise PermanentError(f"Unsupported OCR auth_type: {auth_type}")


def _read_error_body(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8")
    except Exception:
        return ""
    return body.strip() or exc.reason
