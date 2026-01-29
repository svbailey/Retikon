from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Iterable

import numpy as np
from PIL import Image

_BGE_SESSION = None
_BGE_Q_SESSION = None
_CLIP_TEXT_SESSION = None
_CLIP_TEXT_Q_SESSION = None
_CLIP_IMAGE_SESSION = None
_CLAP_AUDIO_SESSION = None
_CLAP_TEXT_SESSION = None

_BGE_TOKENIZER = None
_CLIP_PROCESSOR = None
_CLAP_PROCESSOR = None


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _model_dir() -> str:
    return _env("MODEL_DIR", "/app/models")


def _text_model_name() -> str:
    return _env("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")


def _image_model_name() -> str:
    return _env("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")


def _audio_model_name() -> str:
    return _env("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")


def _onnx_dir(quantized: bool) -> Path:
    base = Path(_model_dir())
    return base / ("onnx-quant" if quantized else "onnx")


def _require_onnxruntime():
    try:
        import importlib

        return importlib.import_module("onnxruntime")
    except ImportError as exc:
        raise RuntimeError(
            "onnxruntime is required for ONNX/quantized embedding backends"
        ) from exc


def _session_options():
    ort = _require_onnxruntime()
    opts = ort.SessionOptions()
    intra = os.getenv("ORT_INTRA_OP_NUM_THREADS") or os.getenv("ORT_NUM_THREADS")
    inter = os.getenv("ORT_INTER_OP_NUM_THREADS")
    if intra:
        opts.intra_op_num_threads = int(intra)
    if inter:
        opts.inter_op_num_threads = int(inter)
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_EXTENDED
    return opts


def _load_session(path: Path):
    if not path.exists():
        raise RuntimeError(f"Missing ONNX model: {path}")
    ort = _require_onnxruntime()
    return ort.InferenceSession(
        path.as_posix(),
        sess_options=_session_options(),
        providers=["CPUExecutionProvider"],
    )


def _normalize(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vectors / norms


def _get_bge_session(quantized: bool):
    global _BGE_SESSION, _BGE_Q_SESSION
    if quantized:
        if _BGE_Q_SESSION is None:
            name = "bge-text-int8.onnx"
            _BGE_Q_SESSION = _load_session(_onnx_dir(True) / name)
        return _BGE_Q_SESSION
    if _BGE_SESSION is None:
        name = "bge-text.onnx"
        _BGE_SESSION = _load_session(_onnx_dir(False) / name)
    return _BGE_SESSION


def _get_clip_text_session(quantized: bool):
    global _CLIP_TEXT_SESSION, _CLIP_TEXT_Q_SESSION
    if quantized:
        if _CLIP_TEXT_Q_SESSION is None:
            name = "clip-text-int8.onnx"
            _CLIP_TEXT_Q_SESSION = _load_session(_onnx_dir(True) / name)
        return _CLIP_TEXT_Q_SESSION
    if _CLIP_TEXT_SESSION is None:
        name = "clip-text.onnx"
        _CLIP_TEXT_SESSION = _load_session(_onnx_dir(False) / name)
    return _CLIP_TEXT_SESSION


def _get_clip_image_session():
    global _CLIP_IMAGE_SESSION
    if _CLIP_IMAGE_SESSION is None:
        name = "clip-image.onnx"
        _CLIP_IMAGE_SESSION = _load_session(_onnx_dir(False) / name)
    return _CLIP_IMAGE_SESSION


def _get_clap_audio_session():
    global _CLAP_AUDIO_SESSION
    if _CLAP_AUDIO_SESSION is None:
        name = "clap-audio.onnx"
        _CLAP_AUDIO_SESSION = _load_session(_onnx_dir(False) / name)
    return _CLAP_AUDIO_SESSION


def _get_clap_text_session():
    global _CLAP_TEXT_SESSION
    if _CLAP_TEXT_SESSION is None:
        name = "clap-text.onnx"
        _CLAP_TEXT_SESSION = _load_session(_onnx_dir(False) / name)
    return _CLAP_TEXT_SESSION


def _get_bge_tokenizer():
    global _BGE_TOKENIZER
    if _BGE_TOKENIZER is None:
        from transformers import AutoTokenizer

        _BGE_TOKENIZER = AutoTokenizer.from_pretrained(
            _text_model_name(),
            cache_dir=_model_dir(),
        )
    return _BGE_TOKENIZER


def _get_clip_processor():
    global _CLIP_PROCESSOR
    if _CLIP_PROCESSOR is None:
        from transformers import CLIPProcessor

        _CLIP_PROCESSOR = CLIPProcessor.from_pretrained(
            _image_model_name(),
            cache_dir=_model_dir(),
        )
    return _CLIP_PROCESSOR


def _get_clap_processor():
    global _CLAP_PROCESSOR
    if _CLAP_PROCESSOR is None:
        from transformers import ClapProcessor

        _CLAP_PROCESSOR = ClapProcessor.from_pretrained(
            _audio_model_name(),
            cache_dir=_model_dir(),
        )
    return _CLAP_PROCESSOR


def _decode_audio_payloads(clips: Iterable[bytes]) -> list[np.ndarray]:
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
    return audio_list


class OnnxTextEmbedder:
    def __init__(self) -> None:
        self._session = _get_bge_session(False)
        self._tokenizer = _get_bge_tokenizer()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = self._tokenizer(
            list(texts),
            return_tensors="np",
            padding=True,
            truncation=True,
        )
        input_ids = inputs["input_ids"].astype("int64")
        attention_mask = inputs["attention_mask"].astype("int64")
        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        vectors = _normalize(outputs[0])
        return vectors.tolist()


class QuantizedTextEmbedder(OnnxTextEmbedder):
    def __init__(self) -> None:
        self._session = _get_bge_session(True)
        self._tokenizer = _get_bge_tokenizer()


class OnnxClipTextEmbedder:
    def __init__(self) -> None:
        self._session = _get_clip_text_session(False)
        self._processor = _get_clip_processor()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = self._processor(
            text=list(texts),
            return_tensors="np",
            padding=True,
        )
        input_ids = inputs["input_ids"].astype("int64")
        attention_mask = inputs["attention_mask"].astype("int64")
        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        vectors = _normalize(outputs[0])
        return vectors.tolist()


class QuantizedClipTextEmbedder(OnnxClipTextEmbedder):
    def __init__(self) -> None:
        self._session = _get_clip_text_session(True)
        self._processor = _get_clip_processor()


class OnnxClipImageEmbedder:
    def __init__(self) -> None:
        self._session = _get_clip_image_session()
        self._processor = _get_clip_processor()

    def encode(self, images: Iterable[Image.Image]) -> list[list[float]]:
        inputs = self._processor(images=list(images), return_tensors="np")
        pixel_values = inputs["pixel_values"].astype("float32")
        outputs = self._session.run(None, {"pixel_values": pixel_values})
        vectors = _normalize(outputs[0])
        return vectors.tolist()


class QuantizedClipImageEmbedder(OnnxClipImageEmbedder):
    pass


class OnnxClapAudioEmbedder:
    def __init__(self) -> None:
        self._session = _get_clap_audio_session()
        self._processor = _get_clap_processor()
        self._input_names = {inp.name for inp in self._session.get_inputs()}

    def encode(self, clips: Iterable[bytes]) -> list[list[float]]:
        audio_list = _decode_audio_payloads(clips)
        inputs = self._processor(
            audios=audio_list,
            sampling_rate=48000,
            return_tensors="np",
            padding=True,
        )
        ort_inputs = {
            "input_features": inputs["input_features"].astype("float32")
        }
        if "attention_mask" in inputs and "attention_mask" in self._input_names:
            ort_inputs["attention_mask"] = inputs["attention_mask"].astype("int64")
        if "is_longer" in self._input_names:
            is_longer = inputs.get("is_longer")
            if is_longer is None:
                is_longer = np.zeros(
                    inputs["input_features"].shape[0],
                    dtype=np.bool_,
                )
            ort_inputs["is_longer"] = np.asarray(is_longer)
        outputs = self._session.run(None, ort_inputs)
        vectors = _normalize(outputs[0])
        return vectors.tolist()


class QuantizedClapAudioEmbedder(OnnxClapAudioEmbedder):
    pass


class OnnxClapTextEmbedder:
    def __init__(self) -> None:
        self._session = _get_clap_text_session()
        self._processor = _get_clap_processor()

    def encode(self, texts: Iterable[str]) -> list[list[float]]:
        inputs = self._processor(
            text=list(texts),
            return_tensors="np",
            padding=True,
        )
        input_ids = inputs["input_ids"].astype("int64")
        attention_mask = inputs["attention_mask"].astype("int64")
        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )
        vectors = _normalize(outputs[0])
        return vectors.tolist()


class QuantizedClapTextEmbedder(OnnxClapTextEmbedder):
    pass
