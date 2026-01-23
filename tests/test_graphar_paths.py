from retikon_core.storage.paths import (
    edge_part_uri,
    graph_root,
    manifest_uri,
    vertex_part_uri,
)


def test_graph_paths():
    base = graph_root("retikon-graph", "retikon_v2")
    assert base == "gs://retikon-graph/retikon_v2"

    vertex_path = vertex_part_uri(base, "DocChunk", "core", "abc123")
    assert (
        vertex_path
        == "gs://retikon-graph/retikon_v2/vertices/DocChunk/core/part-abc123.parquet"
    )

    edge_path = edge_part_uri(base, "DerivedFrom", "edge1")
    assert (
        edge_path
        == "gs://retikon-graph/retikon_v2/edges/DerivedFrom/adj_list/part-edge1.parquet"
    )

    manifest_path = manifest_uri(base, "run-001")
    assert (
        manifest_path
        == "gs://retikon-graph/retikon_v2/manifests/run-001/manifest.json"
    )
