from __future__ import annotations

import os
from typing import Optional

from PIL import Image


def _parse_int(value: Optional[str], default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


def text_embed_batch_size(default: int = 32) -> int:
    raw = os.getenv("TEXT_EMBED_BATCH_SIZE")
    if raw is None or raw == "":
        raw = os.getenv("DOC_EMBED_BATCH_SIZE", str(default))
    value = _parse_int(raw, default)
    return max(1, value)


def image_embed_batch_size(default: int = 8) -> int:
    value = _parse_int(os.getenv("IMAGE_EMBED_BATCH_SIZE"), default)
    return max(1, value)


def image_embed_max_dim(default: int = 0) -> int:
    value = _parse_int(os.getenv("IMAGE_EMBED_MAX_DIM"), default)
    return max(0, value)


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return resampling.LANCZOS


def prepare_image_for_embed(image: Image.Image) -> Image.Image:
    max_dim = image_embed_max_dim()
    if max_dim <= 0:
        return image
    if max(image.size) <= max_dim:
        return image
    resized = image.copy()
    resized.thumbnail((max_dim, max_dim), resample=_resample_filter())
    return resized
