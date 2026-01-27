from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pyarrow as pa
import yaml

SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas" / "graphar"

_TYPE_MAP: dict[str, pa.DataType] = {
    "string": pa.string(),
    "int32": pa.int32(),
    "int64": pa.int64(),
    "timestamp": pa.timestamp("ms"),
}


@dataclass(frozen=True)
class GraphArSchema:
    name: str
    entity: str
    version: int
    data: dict[str, Any]

    def fields(self) -> list[dict[str, Any]]:
        return list(self.data.get("fields", []))


def _schema_path(name: str, schema_root: Path) -> Path:
    return schema_root / name / "prefix.yml"


def load_schema(name: str, schema_root: Path | None = None) -> GraphArSchema:
    root = schema_root or SCHEMA_ROOT
    path = _schema_path(name, root)
    data = yaml.safe_load(path.read_text())
    return GraphArSchema(
        name=data["name"],
        entity=data["entity"],
        version=int(data["version"]),
        data=data,
    )


def load_schemas(schema_root: Path | None = None) -> dict[str, GraphArSchema]:
    root = schema_root or SCHEMA_ROOT
    schemas: dict[str, GraphArSchema] = {}
    for path in sorted(root.glob("*/prefix.yml")):
        data = yaml.safe_load(path.read_text())
        schemas[data["name"]] = GraphArSchema(
            name=data["name"],
            entity=data["entity"],
            version=int(data["version"]),
            data=data,
        )
    return schemas


def _field_type(field: dict[str, Any]) -> pa.DataType:
    type_name = field["type"]
    if type_name == "list<float32>":
        length = field.get("vector_length")
        if length is None:
            raise ValueError("vector_length is required for list<float32> fields")
        if hasattr(pa, "fixed_size_list"):
            return pa.fixed_size_list(pa.float32(), int(length))
        return pa.list_(pa.float32(), list_size=int(length))
    try:
        return _TYPE_MAP[type_name]
    except KeyError as exc:
        raise ValueError(f"Unsupported field type: {type_name}") from exc


def _select_fields(
    schema: GraphArSchema,
    file_kind: str | None,
) -> list[dict[str, Any]]:
    fields = []
    for field in schema.fields():
        target = field.get("file")
        if schema.entity == "edge":
            if file_kind == "adj_list":
                fields.append(field)
            continue
        if file_kind is None or file_kind == "core":
            if target is None:
                fields.append(field)
            continue
        if target == file_kind:
            fields.append(field)
    return fields


def schema_for(
    name: str,
    file_kind: str | None = None,
    schema_root: Path | None = None,
) -> pa.Schema:
    schema = load_schema(name, schema_root)
    fields = _select_fields(schema, file_kind)
    pa_fields = [
        pa.field(field["name"], _field_type(field), nullable=bool(field["nullable"]))
        for field in fields
    ]
    return pa.schema(pa_fields)


def merge_schemas(schemas: Iterable[pa.Schema]) -> pa.Schema:
    merged_fields: dict[str, pa.Field] = {}
    ordered: list[str] = []
    for schema in schemas:
        for field in schema:
            existing = merged_fields.get(field.name)
            if existing is None:
                merged_fields[field.name] = field
                ordered.append(field.name)
                continue
            if existing.type != field.type:
                raise ValueError(
                    f"Schema mismatch for field {field.name}: "
                    f"{existing.type} != {field.type}"
                )
    return pa.schema([merged_fields[name] for name in ordered])
