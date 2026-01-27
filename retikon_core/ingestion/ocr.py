from __future__ import annotations

import shutil

import fitz
from PIL import Image

from retikon_core.errors import PermanentError


def _load_pytesseract():
    try:
        import pytesseract
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


def ocr_text_from_pdf(path: str, max_pages: int) -> str:
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
