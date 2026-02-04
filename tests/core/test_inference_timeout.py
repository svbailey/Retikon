import time

import pytest

from retikon_core.embeddings.timeout import run_inference
from retikon_core.errors import InferenceTimeoutError


def test_inference_timeout_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MODEL_INFERENCE_TIMEOUT_S", raising=False)
    assert run_inference("text", lambda: "ok") == "ok"


def test_inference_timeout_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_INFERENCE_TIMEOUT_S", "0.05")

    def slow() -> str:
        time.sleep(0.2)
        return "late"

    with pytest.raises(InferenceTimeoutError):
        run_inference("text", slow)
