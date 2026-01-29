from __future__ import annotations

import pytest

from retikon_core.data_factory.model_registry import load_models, register_model
from retikon_core.data_factory.training import get_training_job, register_training_job


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


@pytest.mark.core
def test_training_job_references_model(tmp_path):
    base_uri = tmp_path.as_posix()
    model = register_model(
        base_uri=base_uri,
        name="Detector",
        version="2.0",
    )
    job = register_training_job(
        base_uri=base_uri,
        dataset_id="dataset-x",
        model_id=model.id,
        epochs=3,
    )
    fetched = get_training_job(base_uri, job.id)
    assert fetched is not None
    assert fetched.spec.model_id == model.id
