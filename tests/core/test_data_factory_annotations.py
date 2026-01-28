from __future__ import annotations

import pytest

from retikon_core.data_factory.annotations import (
    add_annotation,
    create_dataset,
    list_annotations,
    list_datasets,
)


@pytest.mark.core
def test_dataset_and_annotation_roundtrip(tmp_path):
    base_uri = tmp_path.as_posix()
    dataset_result = create_dataset(
        base_uri=base_uri,
        name="Dataset 1",
        description="demo",
        tags=["a", "b"],
        size=10,
        pipeline_version="v1",
        schema_version="1",
    )
    assert dataset_result.uri
    datasets = list_datasets(base_uri)
    assert datasets
    assert datasets[0]["name"] == "Dataset 1"

    annotation_result = add_annotation(
        base_uri=base_uri,
        dataset_id=datasets[0]["id"],
        media_asset_id="asset-1",
        label="person",
        value="true",
        annotator="qa",
        status="approved",
        pipeline_version="v1",
        schema_version="1",
    )
    assert annotation_result.uri
    annotations = list_annotations(base_uri)
    assert annotations
    assert annotations[0]["label"] == "person"
