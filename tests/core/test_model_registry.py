from __future__ import annotations

import pytest

from retikon_core.data_factory.model_registry import load_models, register_model


@pytest.mark.core
def test_model_registry_roundtrip(tmp_path):
    base_uri = tmp_path.as_posix()
    model = register_model(
        base_uri=base_uri,
        name="Classifier",
        version="1.0",
        task="classification",
        framework="pytorch",
        tags=["vision"],
        metrics={"accuracy": 0.9},
    )
    assert model.id
    models = load_models(base_uri)
    assert len(models) == 1
    assert models[0].name == "Classifier"
    assert models[0].metrics == {"accuracy": 0.9}
