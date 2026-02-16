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


def video_embed_max_dim(default: int = 0) -> int:
    raw = os.getenv("VIDEO_EMBED_MAX_DIM")
    if raw is None or raw == "":
        raw = os.getenv("IMAGE_EMBED_MAX_DIM", str(default))
    value = _parse_int(raw, default)
    return max(0, value)


def thumbnail_jpeg_quality(default: int = 85) -> int:
    value = _parse_int(os.getenv("THUMBNAIL_JPEG_QUALITY"), default)
    return min(100, max(1, value))


def _resample_filter():
    resampling = getattr(Image, "Resampling", Image)
    return resampling.LANCZOS


def _prepare_image_for_embed(image: Image.Image, max_dim: int) -> Image.Image:
    if max_dim <= 0:
        return image
    if max(image.size) <= max_dim:
        return image
    resized = image.copy()
    resized.thumbnail((max_dim, max_dim), resample=_resample_filter())
    return resized


def prepare_image_for_embed(image: Image.Image) -> Image.Image:
    return _prepare_image_for_embed(image, image_embed_max_dim())


def prepare_video_image_for_embed(image: Image.Image) -> Image.Image:
    return _prepare_image_for_embed(image, video_embed_max_dim())
