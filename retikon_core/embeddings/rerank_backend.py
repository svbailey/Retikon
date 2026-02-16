from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Protocol, Sequence


class Reranker(Protocol):
    model_name: str
    backend: str

    def score(self, query: str, documents: Sequence[str]) -> list[float]: ...


def _use_real_models() -> bool:
    return os.getenv("USE_REAL_MODELS") == "1"


def _normalize_backend(raw: str | None) -> str:
    backend = (raw or "hf").strip().lower()
    if backend in {"", "hf", "onnx", "quantized", "stub"}:
        return backend or "hf"
    raise ValueError(f"Unsupported rerank backend: {backend}")


def _batch_size() -> int:
    raw = os.getenv("RERANK_BATCH_SIZE", "8")
    try:
        value = int(raw)
    except ValueError:
        value = 8
    return max(1, value)


def _query_max_tokens() -> int:
    raw = os.getenv("RERANK_QUERY_MAX_TOKENS", "32")
    try:
        value = int(raw)
    except ValueError:
        value = 32
    return max(1, value)


def _doc_max_tokens() -> int:
    raw = os.getenv("RERANK_DOC_MAX_TOKENS", "128")
    try:
        value = int(raw)
    except ValueError:
        value = 128
    return max(1, value)


def _model_name() -> str:
    return os.getenv("RERANK_MODEL_NAME", "cross-encoder/ms-marco-MiniLM-L-6-v2")


def _model_dir() -> Path:
    return Path(os.getenv("MODEL_DIR", "/app/models"))


def _onnx_path(backend: str) -> Path:
    override = os.getenv("RERANK_ONNX_MODEL_PATH")
    if override:
        return Path(override)
    if backend == "quantized":
        return _model_dir() / "onnx-quant" / "reranker-int8.onnx"
    return _model_dir() / "onnx" / "reranker.onnx"


def _tokenize_words(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _truncate_tokens(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    parts = text.split()
    if len(parts) <= limit:
        return text
    return " ".join(parts[:limit])


def _stub_overlap_score(query: str, document: str) -> float:
    q = _tokenize_words(query)
    d = _tokenize_words(document)
    if not q or not d:
        return 0.0
    overlap = len(q & d)
    precision = overlap / float(len(d))
    recall = overlap / float(len(q))
    if precision + recall <= 0:
        return 0.0
    f1 = 2.0 * precision * recall / (precision + recall)
    return max(0.0, min(1.0, f1))


@dataclass
class StubReranker:
    model_name: str = "stub:token-overlap"
    backend: str = "stub"

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        return [_stub_overlap_score(query, doc) for doc in documents]


class HfReranker:
    def __init__(self, model_name: str) -> None:
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.backend = "hf"
        self._model = CrossEncoder(
            model_name,
            max_length=_query_max_tokens() + _doc_max_tokens(),
        )

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []
        query_text = _truncate_tokens(query, _query_max_tokens())
        pairs = [
            (query_text, _truncate_tokens(text, _doc_max_tokens()))
            for text in documents
        ]
        values = self._model.predict(
            pairs,
            batch_size=_batch_size(),
            show_progress_bar=False,
        )
        return [float(value) for value in values]


class OnnxReranker:
    def __init__(self, model_name: str, backend: str) -> None:
        import onnxruntime as ort
        from transformers import AutoTokenizer

        model_path = _onnx_path(backend)
        if not model_path.exists():
            raise RuntimeError(
                f"Missing reranker ONNX model: {model_path}. "
                "Run scripts/export_onnx.py --reranker first."
            )

        self.model_name = model_name
        self.backend = backend
        self._tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=_model_dir())
        self._session = ort.InferenceSession(model_path.as_posix())

    def score(self, query: str, documents: Sequence[str]) -> list[float]:
        if not documents:
            return []

        query_text = _truncate_tokens(query, _query_max_tokens())
        truncated_docs = [
            _truncate_tokens(text, _doc_max_tokens())
            for text in documents
        ]
        scores: list[float] = []
        batch_size = _batch_size()
        max_length = _query_max_tokens() + _doc_max_tokens()
        for start in range(0, len(truncated_docs), batch_size):
            batch = truncated_docs[start : start + batch_size]
            encoded = self._tokenizer(
                [query_text] * len(batch),
                list(batch),
                truncation=True,
                max_length=max_length,
                padding=True,
                return_tensors="np",
            )
            inputs = {
                key: value
                for key, value in encoded.items()
                if key in {"input_ids", "attention_mask", "token_type_ids"}
            }
            outputs = self._session.run(None, inputs)
            if not outputs:
                scores.extend([0.0] * len(batch))
                continue
            logits = outputs[0]
            for row in logits:
                if isinstance(row, (list, tuple)):
                    if len(row) == 0:
                        score = 0.0
                    elif len(row) == 1:
                        score = float(row[0])
                    else:
                        score = float(row[-1])
                else:
                    try:
                        score = float(row)
                    except (TypeError, ValueError):
                        score = 0.0
                scores.append(score)
        return scores


_RERANKER: Reranker | None = None
_RERANKER_KEY: tuple[str, str, bool] | None = None


def get_reranker() -> Reranker:
    global _RERANKER, _RERANKER_KEY

    backend = _normalize_backend(os.getenv("RERANK_BACKEND", "hf"))
    model_name = _model_name()
    use_real = _use_real_models()
    key = (backend, model_name, use_real)
    if _RERANKER is not None and _RERANKER_KEY == key:
        return _RERANKER

    if backend == "stub" or not use_real:
        _RERANKER = StubReranker()
        _RERANKER_KEY = key
        return _RERANKER

    if backend == "hf":
        _RERANKER = HfReranker(model_name)
        _RERANKER_KEY = key
        return _RERANKER

    if backend in {"onnx", "quantized"}:
        _RERANKER = OnnxReranker(model_name, backend)
        _RERANKER_KEY = key
        return _RERANKER

    _RERANKER = StubReranker()
    _RERANKER_KEY = key
    return _RERANKER


def reset_reranker_cache() -> None:
    global _RERANKER, _RERANKER_KEY
    _RERANKER = None
    _RERANKER_KEY = None


def normalize_rerank_scores(scores: Sequence[float]) -> list[float]:
    if not scores:
        return []
    minimum = min(scores)
    maximum = max(scores)
    if minimum >= 0.0 and maximum <= 1.0:
        return [float(value) for value in scores]
    if math.isclose(minimum, maximum):
        return [0.5 for _ in scores]
    return [1.0 / (1.0 + math.exp(-float(value))) for value in scores]
