from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("onnxruntime")

from retikon_core.embeddings.onnx_backend import (  # noqa: E402
    OnnxClapAudioEmbedder,
    OnnxClapTextEmbedder,
    OnnxClipTextEmbedder,
    OnnxTextEmbedder,
    QuantizedClipTextEmbedder,
    QuantizedTextEmbedder,
)
from retikon_core.embeddings.stub import (  # noqa: E402
    RealClapAudioEmbedder,
    RealClapTextEmbedder,
    RealClipTextEmbedder,
    RealTextEmbedder,
)


def _model_dir() -> Path:
    return Path(os.getenv("MODEL_DIR", "/app/models"))


def _onnx_path(name: str, quantized: bool = False) -> Path:
    base = _model_dir() / ("onnx-quant" if quantized else "onnx")
    return base / name


def _require_onnx_files(paths: list[Path]) -> None:
    missing = [path for path in paths if not path.exists()]
    if missing:
        pytest.skip(
            "ONNX model assets missing: "
            + ", ".join(path.as_posix() for path in missing)
        )


def _cosine(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    denom = np.linalg.norm(va) * np.linalg.norm(vb)
    if denom == 0:
        return 0.0
    return float(np.dot(va, vb) / denom)


@pytest.mark.core
def test_onnx_text_similarity() -> None:
    _require_onnx_files([_onnx_path("bge-text.onnx")])
    hf = RealTextEmbedder()
    onnx = OnnxTextEmbedder()
    inputs = ["retikon demo query", "another test sentence"]
    hf_vecs = hf.encode(inputs)
    onnx_vecs = onnx.encode(inputs)
    sims = [_cosine(hf_vecs[i], onnx_vecs[i]) for i in range(len(inputs))]
    assert min(sims) >= 0.98


@pytest.mark.core
def test_onnx_clip_text_similarity() -> None:
    _require_onnx_files([_onnx_path("clip-text.onnx")])
    hf = RealClipTextEmbedder()
    onnx = OnnxClipTextEmbedder()
    inputs = ["retikon image query", "clip text baseline"]
    hf_vecs = hf.encode(inputs)
    onnx_vecs = onnx.encode(inputs)
    sims = [_cosine(hf_vecs[i], onnx_vecs[i]) for i in range(len(inputs))]
    assert min(sims) >= 0.98


@pytest.mark.core
def test_onnx_clap_text_similarity() -> None:
    _require_onnx_files([_onnx_path("clap-text.onnx")])
    hf = RealClapTextEmbedder()
    onnx = OnnxClapTextEmbedder()
    inputs = ["retikon audio query", "clap text baseline"]
    hf_vecs = hf.encode(inputs)
    onnx_vecs = onnx.encode(inputs)
    sims = [_cosine(hf_vecs[i], onnx_vecs[i]) for i in range(len(inputs))]
    assert min(sims) >= 0.97


@pytest.mark.core
def test_onnx_clap_audio_similarity() -> None:
    _require_onnx_files([_onnx_path("clap-audio.onnx")])
    audio_path = Path(__file__).resolve().parents[1] / "fixtures" / "sample.wav"
    if not audio_path.exists():
        pytest.skip(f"Missing fixture: {audio_path}")
    payload = audio_path.read_bytes()
    hf = RealClapAudioEmbedder()
    onnx = OnnxClapAudioEmbedder()
    hf_vecs = hf.encode([payload])
    onnx_vecs = onnx.encode([payload])
    sim = _cosine(hf_vecs[0], onnx_vecs[0])
    assert sim >= 0.97


@pytest.mark.core
def test_quantized_text_similarity() -> None:
    _require_onnx_files(
        [_onnx_path("bge-text-int8.onnx", quantized=True)]
    )
    hf = RealTextEmbedder()
    onnx = QuantizedTextEmbedder()
    inputs = ["retikon demo query", "another test sentence"]
    hf_vecs = hf.encode(inputs)
    onnx_vecs = onnx.encode(inputs)
    sims = [_cosine(hf_vecs[i], onnx_vecs[i]) for i in range(len(inputs))]
    assert min(sims) >= 0.95


@pytest.mark.core
def test_quantized_clip_text_similarity() -> None:
    _require_onnx_files(
        [_onnx_path("clip-text-int8.onnx", quantized=True)]
    )
    hf = RealClipTextEmbedder()
    onnx = QuantizedClipTextEmbedder()
    inputs = ["retikon image query", "clip text baseline"]
    hf_vecs = hf.encode(inputs)
    onnx_vecs = onnx.encode(inputs)
    sims = [_cosine(hf_vecs[i], onnx_vecs[i]) for i in range(len(inputs))]
    assert min(sims) >= 0.95
