from __future__ import annotations

import hashlib
import os
import random
from typing import Iterable, Protocol


class TextEmbedder(Protocol):
    def encode(self, texts: Iterable[str]) -> list[list[float]]: ...


class ImageEmbedder(Protocol):
    def encode(self, images: Iterable[bytes]) -> list[list[float]]: ...


def _seed_from_bytes(payload: bytes) -> int:
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big")


def _deterministic_vector(seed: int, dim: int) -> list[float]:
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(dim)]


class StubTextEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            seed = _seed_from_bytes(text.encode("utf-8"))
            vectors.append(_deterministic_vector(seed, self.dim))
        return vectors


class StubImageEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def encode(self, images: Iterable[bytes]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for payload in images:
            seed = _seed_from_bytes(payload)
            vectors.append(_deterministic_vector(seed, self.dim))
        return vectors


def get_text_embedder(dim: int) -> TextEmbedder:
    if os.getenv("USE_REAL_MODELS") == "1":
        raise RuntimeError("Real text embedder is not wired yet.")
    return StubTextEmbedder(dim)


def get_image_embedder(dim: int) -> ImageEmbedder:
    if os.getenv("USE_REAL_MODELS") == "1":
        raise RuntimeError("Real image embedder is not wired yet.")
    return StubImageEmbedder(dim)
