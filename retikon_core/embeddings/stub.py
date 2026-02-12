from __future__ import annotations

import hashlib
import io
import os
import random
from typing import Any, Callable, Iterable, Protocol, TypeVar

from PIL import Image

from retikon_core.embeddings.onnx_backend import (
    OnnxClapAudioEmbedder as BackendOnnxClapAudioEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    OnnxClapTextEmbedder as BackendOnnxClapTextEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    OnnxClipImageEmbedder as BackendOnnxClipImageEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    OnnxClipTextEmbedder as BackendOnnxClipTextEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    OnnxTextEmbedder as BackendOnnxTextEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    QuantizedClapAudioEmbedder as BackendQuantizedClapAudioEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    QuantizedClapTextEmbedder as BackendQuantizedClapTextEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    QuantizedClipImageEmbedder as BackendQuantizedClipImageEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    QuantizedClipTextEmbedder as BackendQuantizedClipTextEmbedder,
)
from retikon_core.embeddings.onnx_backend import (
    QuantizedTextEmbedder as BackendQuantizedTextEmbedder,
)


class TextEmbedder(Protocol):
    def encode(self, texts: Iterable[str]) -> list[list[float]]: ...


class ImageEmbedder(Protocol):
    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]: ...


class AudioEmbedder(Protocol):
    def encode(self, clips: Iterable[bytes]) -> list[list[float]]: ...


BACKEND_STUB = "stub"
BACKEND_HF = "hf"
BACKEND_ONNX = "onnx"
BACKEND_QUANTIZED = "quantized"
BACKEND_AUTO = "auto"


def _use_real_models() -> bool:
    return os.getenv("USE_REAL_MODELS") == "1"


def _normalize_backend(raw: str | None) -> str:
    backend = (raw or BACKEND_AUTO).strip().lower()
    if backend in {"", BACKEND_AUTO}:
        return BACKEND_HF if _use_real_models() else BACKEND_STUB
    if backend in {"transformers", "real"}:
        return BACKEND_HF
    if backend in {BACKEND_STUB, BACKEND_HF, BACKEND_ONNX, BACKEND_QUANTIZED}:
        return backend
    raise ValueError(f"Unsupported embedding backend: {backend}")


def _embedding_backend() -> str:
    raw = os.getenv("EMBEDDING_BACKEND") or os.getenv("RETIKON_EMBEDDING_BACKEND")
    return _normalize_backend(raw)


def _embedding_backend_for(kind: str, fallback_kind: str | None = None) -> str:
    kind_key = f"{kind.upper()}_EMBED_BACKEND"
    specific = os.getenv(kind_key)
    if specific:
        return _normalize_backend(specific)
    if fallback_kind:
        fallback = os.getenv(f"{fallback_kind.upper()}_EMBED_BACKEND")
        if fallback:
            return _normalize_backend(fallback)
    return _embedding_backend()


def _model_dir() -> str:
    return os.getenv("MODEL_DIR", "/app/models")


def _text_model_name() -> str:
    return os.getenv("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _text_model_max_tokens() -> int:
    raw = os.getenv("TEXT_MODEL_MAX_TOKENS")
    if raw is None or raw == "":
        return 512
    try:
        value = int(raw)
    except ValueError:
        return 512
    return value if value > 0 else 512


def _image_model_name() -> str:
    return os.getenv("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _audio_model_name() -> str:
    return os.getenv("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _embedding_device() -> str:
    return os.getenv("EMBEDDING_DEVICE", "cpu")


_CLIP_BUNDLE: tuple[Any, Any, str] | None = None
_CLAP_BUNDLE: tuple[Any, Any, str] | None = None


def _get_clip_bundle() -> tuple[Any, Any, str]:
    global _CLIP_BUNDLE
    device = _embedding_device()
    if _CLIP_BUNDLE is None or _CLIP_BUNDLE[2] != device:
        from transformers import CLIPModel, CLIPProcessor

        model_name = _image_model_name()
        cache_dir = _model_dir()
        model = CLIPModel.from_pretrained(model_name, cache_dir=cache_dir)
        processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model.to(device)
        model.eval()
        _CLIP_BUNDLE = (model, processor, device)
    return _CLIP_BUNDLE


def _get_clap_bundle() -> tuple[Any, Any, str]:
    global _CLAP_BUNDLE
    device = _embedding_device()
    if _CLAP_BUNDLE is None or _CLAP_BUNDLE[2] != device:
        from transformers import ClapModel, ClapProcessor

        model_name = _audio_model_name()
        cache_dir = _model_dir()
        model = ClapModel.from_pretrained(model_name, cache_dir=cache_dir)
        processor = ClapProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model.to(device)
        model.eval()
        _CLAP_BUNDLE = (model, processor, device)
    return _CLAP_BUNDLE


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
        from transformers import AutoTokenizer

        self.model = SentenceTransformer(
            _text_model_name(),
            cache_folder=_model_dir(),
            device=_embedding_device(),
        )
        self._max_tokens = _text_model_max_tokens()
        self._tokenizer = AutoTokenizer.from_pretrained(
            _text_model_name(),
            cache_dir=_model_dir(),
            use_fast=True,
        )
        if hasattr(self.model, "max_seq_length"):
            self.model.max_seq_length = self._max_tokens

    def _truncate_texts(self, texts: list[str]) -> list[str]:
        if not texts:
            return texts
        if self._max_tokens <= 0:
            return texts
        encoded = self._tokenizer(
            texts,
            truncation=True,
            max_length=self._max_tokens,
            add_special_tokens=False,
        )
        input_ids = encoded.get("input_ids")
        if not input_ids:
            return texts
        return self._tokenizer.batch_decode(input_ids, skip_special_tokens=True)

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = list(texts)
        inputs = self._truncate_texts(inputs)
        vectors = self.model.encode(
            inputs,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        return vectors.tolist()


class RealClipImageEmbedder:
    def __init__(self) -> None:
        model, processor, device = _get_clip_bundle()
        self.model = model
        self.processor = processor
        self.device = device

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
        model, processor, device = _get_clip_bundle()
        self.model = model
        self.processor = processor
        self.device = device

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
        model, processor, device = _get_clap_bundle()
        self.model = model
        self.processor = processor
        self.device = device

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
        model, processor, device = _get_clap_bundle()
        self.model = model
        self.processor = processor
        self.device = device

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        import torch

        inputs = self.processor(text=list(texts), return_tensors="pt", padding=True)
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with torch.no_grad():
            features = self.model.get_text_features(**inputs)
            features = torch.nn.functional.normalize(features, p=2, dim=-1)
        return features.cpu().numpy().tolist()


def _require_onnxruntime() -> None:
    try:
        import importlib

        _ = importlib.import_module("onnxruntime")
    except ImportError as exc:  # pragma: no cover - depends on optional deps
        raise RuntimeError(
            "onnxruntime is required for ONNX/quantized embedding backends"
        ) from exc


class OnnxTextEmbedder:
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendOnnxTextEmbedder()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        return self._backend.encode(texts)


class OnnxClipImageEmbedder:
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendOnnxClipImageEmbedder()

    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]:
        return self._backend.encode(images)


class OnnxClipTextEmbedder:
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendOnnxClipTextEmbedder()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        return self._backend.encode(texts)


class OnnxClapAudioEmbedder:
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendOnnxClapAudioEmbedder()

    def encode(self, clips: Iterable[bytes]) -> list[list[float]]:
        return self._backend.encode(clips)


class OnnxClapTextEmbedder:
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendOnnxClapTextEmbedder()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        return self._backend.encode(texts)


class QuantizedTextEmbedder(OnnxTextEmbedder):
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendQuantizedTextEmbedder()


class QuantizedClipImageEmbedder(OnnxClipImageEmbedder):
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendQuantizedClipImageEmbedder()


class QuantizedClipTextEmbedder(OnnxClipTextEmbedder):
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendQuantizedClipTextEmbedder()


class QuantizedClapAudioEmbedder(OnnxClapAudioEmbedder):
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendQuantizedClapAudioEmbedder()


class QuantizedClapTextEmbedder(OnnxClapTextEmbedder):
    def __init__(self) -> None:
        _require_onnxruntime()
        self._backend = BackendQuantizedClapTextEmbedder()


_TEXT_CACHE: dict[int, StubTextEmbedder] = {}
_IMAGE_CACHE: dict[int, StubImageEmbedder] = {}
_AUDIO_CACHE: dict[int, StubAudioEmbedder] = {}

_REAL_TEXT: RealTextEmbedder | None = None
_REAL_IMAGE: RealClipImageEmbedder | None = None
_REAL_IMAGE_TEXT: RealClipTextEmbedder | None = None
_REAL_AUDIO: RealClapAudioEmbedder | None = None
_REAL_AUDIO_TEXT: RealClapTextEmbedder | None = None

_ONNX_TEXT: "OnnxTextEmbedder | None" = None
_ONNX_IMAGE: "OnnxClipImageEmbedder | None" = None
_ONNX_IMAGE_TEXT: "OnnxClipTextEmbedder | None" = None
_ONNX_AUDIO: "OnnxClapAudioEmbedder | None" = None
_ONNX_AUDIO_TEXT: "OnnxClapTextEmbedder | None" = None

_QUANT_TEXT: "QuantizedTextEmbedder | None" = None
_QUANT_IMAGE: "QuantizedClipImageEmbedder | None" = None
_QUANT_IMAGE_TEXT: "QuantizedClipTextEmbedder | None" = None
_QUANT_AUDIO: "QuantizedClapAudioEmbedder | None" = None
_QUANT_AUDIO_TEXT: "QuantizedClapTextEmbedder | None" = None

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
    backend = _embedding_backend_for("text")
    if backend == BACKEND_STUB or not _use_real_models():
        return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)
    if backend == BACKEND_HF:
        return _get_real_text_embedder()
    if backend == BACKEND_ONNX:
        global _ONNX_TEXT
        if _ONNX_TEXT is None:
            _ONNX_TEXT = OnnxTextEmbedder()
        return _ONNX_TEXT
    if backend == BACKEND_QUANTIZED:
        global _QUANT_TEXT
        if _QUANT_TEXT is None:
            _QUANT_TEXT = QuantizedTextEmbedder()
        return _QUANT_TEXT
    return _get_real_text_embedder()


def get_image_embedder(dim: int) -> ImageEmbedder:
    backend = _embedding_backend_for("image")
    if backend == BACKEND_STUB or not _use_real_models():
        return _get_cached_embedder(_IMAGE_CACHE, StubImageEmbedder, dim)
    if backend == BACKEND_HF:
        return _get_real_image_embedder()
    if backend == BACKEND_ONNX:
        global _ONNX_IMAGE
        if _ONNX_IMAGE is None:
            _ONNX_IMAGE = OnnxClipImageEmbedder()
        return _ONNX_IMAGE
    if backend == BACKEND_QUANTIZED:
        global _QUANT_IMAGE
        if _QUANT_IMAGE is None:
            _QUANT_IMAGE = QuantizedClipImageEmbedder()
        return _QUANT_IMAGE
    return _get_real_image_embedder()


def get_image_text_embedder(dim: int) -> TextEmbedder:
    backend = _embedding_backend_for("image_text", "image")
    if backend == BACKEND_STUB or not _use_real_models():
        return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)
    if backend == BACKEND_HF:
        return _get_real_image_text_embedder()
    if backend == BACKEND_ONNX:
        global _ONNX_IMAGE_TEXT
        if _ONNX_IMAGE_TEXT is None:
            _ONNX_IMAGE_TEXT = OnnxClipTextEmbedder()
        return _ONNX_IMAGE_TEXT
    if backend == BACKEND_QUANTIZED:
        global _QUANT_IMAGE_TEXT
        if _QUANT_IMAGE_TEXT is None:
            _QUANT_IMAGE_TEXT = QuantizedClipTextEmbedder()
        return _QUANT_IMAGE_TEXT
    return _get_real_image_text_embedder()


def get_audio_embedder(dim: int) -> AudioEmbedder:
    backend = _embedding_backend_for("audio")
    if backend == BACKEND_STUB or not _use_real_models():
        return _get_cached_embedder(_AUDIO_CACHE, StubAudioEmbedder, dim)
    if backend == BACKEND_HF:
        return _get_real_audio_embedder()
    if backend == BACKEND_ONNX:
        global _ONNX_AUDIO
        if _ONNX_AUDIO is None:
            _ONNX_AUDIO = OnnxClapAudioEmbedder()
        return _ONNX_AUDIO
    if backend == BACKEND_QUANTIZED:
        global _QUANT_AUDIO
        if _QUANT_AUDIO is None:
            _QUANT_AUDIO = QuantizedClapAudioEmbedder()
        return _QUANT_AUDIO
    return _get_real_audio_embedder()


def get_audio_text_embedder(dim: int) -> TextEmbedder:
    backend = _embedding_backend_for("audio_text", "audio")
    if backend == BACKEND_STUB or not _use_real_models():
        return _get_cached_embedder(_TEXT_CACHE, StubTextEmbedder, dim)
    if backend == BACKEND_HF:
        return _get_real_audio_text_embedder()
    if backend == BACKEND_ONNX:
        global _ONNX_AUDIO_TEXT
        if _ONNX_AUDIO_TEXT is None:
            _ONNX_AUDIO_TEXT = OnnxClapTextEmbedder()
        return _ONNX_AUDIO_TEXT
    if backend == BACKEND_QUANTIZED:
        global _QUANT_AUDIO_TEXT
        if _QUANT_AUDIO_TEXT is None:
            _QUANT_AUDIO_TEXT = QuantizedClapTextEmbedder()
        return _QUANT_AUDIO_TEXT
    return _get_real_audio_text_embedder()


def get_embedding_backend(kind: str | None = None) -> str:
    if kind is None:
        return _embedding_backend()
    kind = kind.strip().lower()
    if kind in {"image_text", "clip_text"}:
        return _embedding_backend_for("image_text", "image")
    if kind in {"audio_text", "clap_text"}:
        return _embedding_backend_for("audio_text", "audio")
    return _embedding_backend_for(kind)


def reset_embedding_cache() -> None:
    _TEXT_CACHE.clear()
    _IMAGE_CACHE.clear()
    _AUDIO_CACHE.clear()
    global _REAL_TEXT, _REAL_IMAGE, _REAL_IMAGE_TEXT, _REAL_AUDIO, _REAL_AUDIO_TEXT
    global _ONNX_TEXT, _ONNX_IMAGE, _ONNX_IMAGE_TEXT, _ONNX_AUDIO, _ONNX_AUDIO_TEXT
    global _QUANT_TEXT, _QUANT_IMAGE, _QUANT_IMAGE_TEXT, _QUANT_AUDIO, _QUANT_AUDIO_TEXT
    _REAL_TEXT = None
    _REAL_IMAGE = None
    _REAL_IMAGE_TEXT = None
    _REAL_AUDIO = None
    _REAL_AUDIO_TEXT = None
    _ONNX_TEXT = None
    _ONNX_IMAGE = None
    _ONNX_IMAGE_TEXT = None
    _ONNX_AUDIO = None
    _ONNX_AUDIO_TEXT = None
    _QUANT_TEXT = None
    _QUANT_IMAGE = None
    _QUANT_IMAGE_TEXT = None
    _QUANT_AUDIO = None
    _QUANT_AUDIO_TEXT = None
