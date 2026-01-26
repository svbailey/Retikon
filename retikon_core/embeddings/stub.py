from __future__ import annotations

import hashlib
import io
import os
import random
from typing import Callable, Iterable, Protocol, TypeVar

from PIL import Image


class TextEmbedder(Protocol):
    def encode(self, texts: Iterable[str]) -> list[list[float]]: ...


class ImageEmbedder(Protocol):
    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]: ...


class AudioEmbedder(Protocol):
    def encode(self, clips: Iterable[bytes]) -> list[list[float]]: ...


def _use_real_models() -> bool:
    return os.getenv("USE_REAL_MODELS") == "1"


def _model_dir() -> str:
    return os.getenv("MODEL_DIR", "/app/models")


def _text_model_name() -> str:
    return os.getenv("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _image_model_name() -> str:
    return os.getenv("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _audio_model_name() -> str:
    return os.getenv("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _embedding_device() -> str:
    return os.getenv("EMBEDDING_DEVICE", "cpu")


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

    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for image in images:
            seed = _seed_from_bytes(image.tobytes())
            vectors.append(_deterministic_vector(seed, self.dim))
        return vectors


class StubAudioEmbedder:
    def __init__(self, dim: int) -> None:
        self.dim = dim

    def encode(self, clips: Iterable[bytes]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for payload in clips:
            seed = _seed_from_bytes(payload)
            vectors.append(_deterministic_vector(seed, self.dim))
        return vectors


class RealTextEmbedder:
    def __init__(self) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            _text_model_name(),
            cache_folder=_model_dir(),
            device=_embedding_device(),
        )

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = list(texts)
        vectors = self.model.encode(
            inputs,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()


class RealClipImageEmbedder:
    def __init__(self) -> None:
        from transformers import CLIPModel, CLIPProcessor

        model_name = _image_model_name()
        cache_dir = _model_dir()
        self.device = _embedding_device()
        self.model = CLIPModel.from_pretrained(model_name, cache_dir=cache_dir)
        self.processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        self.model.to(self.device)
        self.model.eval()

    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]:
        import torch

        inputs = self.processor(images=list(images), return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            features = self.model.get_image_features(**inputs)
            features = torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


class RealClipTextEmbedder:
    def __init__(self) -> None:
        from transformers import CLIPModel, CLIPProcessor

        model_name = _image_model_name()
        cache_dir = _model_dir()
        self.device = _embedding_device()
        self.model = CLIPModel.from_pretrained(model_name, cache_dir=cache_dir)
        self.processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        self.model.to(self.device)
        self.model.eval()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        import torch

        inputs = self.processor(text=list(texts), return_tensors="pt", padding=True)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            features = self.model.get_text_features(**inputs)
            features = torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


class RealClapAudioEmbedder:
    def __init__(self) -> None:
        from transformers import ClapModel, ClapProcessor

        model_name = _audio_model_name()
        cache_dir = _model_dir()
        self.device = _embedding_device()
        self.model = ClapModel.from_pretrained(model_name, cache_dir=cache_dir)
        self.processor = ClapProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        self.model.to(self.device)
        self.model.eval()

    def encode(self, clips: Iterable[bytes]) -> list[list[float]]:
        import numpy as np
        import soundfile as sf
        import torch
        import torchaudio

        audio_list: list[np.ndarray] = []
        for payload in clips:
            data, sample_rate = sf.read(io.BytesIO(payload), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sample_rate != 48000:
                tensor = torch.from_numpy(data)
                tensor = torchaudio.functional.resample(
                    tensor,
                    sample_rate,
                    48000,
                )
                data = tensor.numpy()
                sample_rate = 48000
            audio_list.append(data)

        inputs = self.processor(
            audios=audio_list,
            sampling_rate=48000,
            return_tensors="pt",
            padding=True,
        )
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            features = self.model.get_audio_features(**inputs)
            features = torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


class RealClapTextEmbedder:
    def __init__(self) -> None:
        from transformers import ClapModel, ClapProcessor

        model_name = _audio_model_name()
        cache_dir = _model_dir()
        self.device = _embedding_device()
        self.model = ClapModel.from_pretrained(model_name, cache_dir=cache_dir)
        self.processor = ClapProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        self.model.to(self.device)
        self.model.eval()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        import torch

        inputs = self.processor(text=list(texts), return_tensors="pt", padding=True)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            features = self.model.get_text_features(**inputs)
            features = torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


_TEXT_CACHE: dict[int, StubTextEmbedder] = {}
_IMAGE_CACHE: dict[int, StubImageEmbedder] = {}
_AUDIO_CACHE: dict[int, StubAudioEmbedder] = {}

_REAL_TEXT: RealTextEmbedder | None = None
_REAL_IMAGE: RealClipImageEmbedder | None = None
_REAL_IMAGE_TEXT: RealClipTextEmbedder | None = None
_REAL_AUDIO: RealClapAudioEmbedder | None = None
_REAL_AUDIO_TEXT: RealClapTextEmbedder | None = None

EmbedderT = TypeVar("EmbedderT")


def _get_cached_embedder(
    cache: dict[int, EmbedderT],
    factory: Callable[[int], EmbedderT],
    dim: int,
) -> EmbedderT:
    embedder = cache.get(dim)
    if embedder is None:
        embedder = factory(dim)
        cache[dim] = embedder
    return embedder


def _get_real_text_embedder() -> TextEmbedder:
    global _REAL_TEXT
    if _REAL_TEXT is None:
        _REAL_TEXT = RealTextEmbedder()
    return _REAL_TEXT


def _get_real_image_embedder() -> ImageEmbedder:
    global _REAL_IMAGE
    if _REAL_IMAGE is None:
        _REAL_IMAGE = RealClipImageEmbedder()
    return _REAL_IMAGE


def _get_real_image_text_embedder() -> TextEmbedder:
    global _REAL_IMAGE_TEXT
    if _REAL_IMAGE_TEXT is None:
        _REAL_IMAGE_TEXT = RealClipTextEmbedder()
    return _REAL_IMAGE_TEXT


def _get_real_audio_embedder() -> AudioEmbedder:
    global _REAL_AUDIO
    if _REAL_AUDIO is None:
        _REAL_AUDIO = RealClapAudioEmbedder()
    return _REAL_AUDIO


def _get_real_audio_text_embedder() -> TextEmbedder:
    global _REAL_AUDIO_TEXT
    if _REAL_AUDIO_TEXT is None:
        _REAL_AUDIO_TEXT = RealClapTextEmbedder()
    return _REAL_AUDIO_TEXT


def get_text_embedder(dim: int) -> TextEmbedder:
    if _use_real_models():
        return _get_real_text_embedder()
    return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)


def get_image_embedder(dim: int) -> ImageEmbedder:
    if _use_real_models():
        return _get_real_image_embedder()
    return _get_cached_embedder(_IMAGE_CACHE, StubImageEmbedder, dim)


def get_image_text_embedder(dim: int) -> TextEmbedder:
    if _use_real_models():
        return _get_real_image_text_embedder()
    return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)


def get_audio_embedder(dim: int) -> AudioEmbedder:
    if _use_real_models():
        return _get_real_audio_embedder()
    return _get_cached_embedder(_AUDIO_CACHE, StubAudioEmbedder, dim)


def get_audio_text_embedder(dim: int) -> TextEmbedder:
    if _use_real_models():
        return _get_real_audio_text_embedder()
    return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)
