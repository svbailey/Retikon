import pyarrow as pa

from retikon_core.storage.schemas import merge_schemas, schema_for


def test_docchunk_schema_split():
    core = schema_for("DocChunk", "core")
    assert core.names == [
        "id",
        "media_asset_id",
        "org_id",
        "site_id",
        "stream_id",
        "chunk_index",
        "char_start",
        "char_end",
        "token_start",
        "token_end",
        "token_count",
        "source_type",
        "source_ref_id",
        "source_time_ms",
        "ocr_conf_avg",
        "embedding_model",
        "embedding_backend",
        "embedding_artifact",
        "pipeline_version",
        "schema_version",
    ]

    text = schema_for("DocChunk", "text")
    assert text.names == ["content"]

    vector = schema_for("DocChunk", "vector")
    assert vector.names == ["text_vector"]
    assert vector.field("text_vector").type.list_size == 768


def test_vector_lengths():
    transcript_core = schema_for("Transcript", "core")
    assert "embedding_backend" in transcript_core.names
    assert "embedding_artifact" in transcript_core.names

    image_core = schema_for("ImageAsset", "core")
    assert "embedding_backend" in image_core.names
    assert "embedding_artifact" in image_core.names

    audio_core = schema_for("AudioClip", "core")
    assert "embedding_backend" in audio_core.names
    assert "embedding_artifact" in audio_core.names

    audio_segment_core = schema_for("AudioSegment", "core")
    assert "embedding_backend" in audio_segment_core.names
    assert "embedding_artifact" in audio_segment_core.names

    clip_vector = schema_for("ImageAsset", "vector").field("clip_vector")
    assert clip_vector.type.list_size == 512

    clap_vector = schema_for("AudioClip", "vector").field("clap_embedding")
    assert clap_vector.type.list_size == 512

    segment_vector = schema_for("AudioSegment", "vector").field("clap_embedding")
    assert segment_vector.type.list_size == 512


def test_schema_merge_union():
    schema_v1 = pa.schema([pa.field("id", pa.string()), pa.field("name", pa.string())])
    schema_v2 = pa.schema([pa.field("id", pa.string()), pa.field("extra", pa.int32())])
    merged = merge_schemas([schema_v1, schema_v2])
    assert merged.names == ["id", "name", "extra"]
