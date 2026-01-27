from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

SCHEMA_ROOT = Path(__file__).resolve().parents[1] / "schemas" / "graphar"

ALLOWED_TYPES = {"string", "int32", "int64", "timestamp", "list<float32>"}
VERTEX_FILES = {"core", "text", "vector"}
EDGE_FILES = {"adj_list"}


@dataclass(frozen=True)
class ValidationError:
    path: Path
    message: str


def _load_schema(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text())


def _validate_schema(path: Path, data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    name = data.get("name")
    entity = data.get("entity")
    path_prefix = data.get("path_prefix")
    files = data.get("files", {})
    fields = data.get("fields", [])

    for key in ("version", "name", "entity", "path_prefix", "files", "fields"):
        if key not in data:
            errors.append(ValidationError(path, f"Missing required key: {key}"))

    if entity not in ("vertex", "edge"):
        errors.append(ValidationError(path, f"Invalid entity type: {entity}"))

    if entity == "vertex":
        if "core" not in files:
            errors.append(ValidationError(path, "Vertex schema missing core file"))
        if data.get("primary_key") is None:
            errors.append(ValidationError(path, "Vertex schema missing primary_key"))
        expected_prefix = f"vertices/{name}"
        if path_prefix != expected_prefix:
            errors.append(
                ValidationError(
                    path,
                    f"path_prefix must be {expected_prefix} for vertex {name}",
                )
            )
        for file_key, file_path in files.items():
            if file_key not in VERTEX_FILES:
                errors.append(
                    ValidationError(path, f"Unexpected vertex file key: {file_key}")
                )
            if not str(file_path).startswith(expected_prefix):
                errors.append(
                    ValidationError(
                        path,
                        f"File path {file_path} must start with {expected_prefix}",
                    )
                )
    elif entity == "edge":
        if "adj_list" not in files:
            errors.append(ValidationError(path, "Edge schema missing adj_list file"))
        expected_prefix = f"edges/{name}"
        if path_prefix != expected_prefix:
            errors.append(
                ValidationError(
                    path,
                    f"path_prefix must be {expected_prefix} for edge {name}",
                )
            )
        for file_key, file_path in files.items():
            if file_key not in EDGE_FILES:
                errors.append(
                    ValidationError(path, f"Unexpected edge file key: {file_key}")
                )
            if not str(file_path).startswith(expected_prefix):
                errors.append(
                    ValidationError(
                        path,
                        f"File path {file_path} must start with {expected_prefix}",
                    )
                )

    for field in fields:
        field_name = field.get("name")
        field_type = field.get("type")
        if field_name is None:
            errors.append(ValidationError(path, "Field missing name"))
        if field_type not in ALLOWED_TYPES:
            errors.append(
                ValidationError(
                    path,
                    f"Field {field_name} has invalid type: {field_type}",
                )
            )
        if "nullable" not in field:
            errors.append(ValidationError(path, f"Field {field_name} missing nullable"))
        if field_type == "list<float32>":
            if field.get("vector_length") is None:
                errors.append(
                    ValidationError(
                        path,
                        f"Field {field_name} missing vector_length",
                    )
                )
        target_file = field.get("file")
        if target_file is not None:
            if entity == "vertex" and target_file not in files:
                errors.append(
                    ValidationError(
                        path,
                        f"Field {field_name} references missing file {target_file}",
                    )
                )
            if entity == "edge":
                errors.append(
                    ValidationError(
                        path,
                        f"Edge field {field_name} must not declare file",
                    )
                )

    schema_field = next(
        (field for field in fields if field.get("name") == "schema_version"),
        None,
    )
    if schema_field is None:
        errors.append(ValidationError(path, "Missing schema_version field"))
    elif schema_field.get("type") != "string":
        errors.append(
            ValidationError(path, "schema_version field must be type string")
        )

    return errors


def validate_all(schema_root: Path | None = None) -> list[ValidationError]:
    root = schema_root or SCHEMA_ROOT
    errors: list[ValidationError] = []
    for path in sorted(root.glob("*/prefix.yml")):
        data = _load_schema(path)
        errors.extend(_validate_schema(path, data))
    return errors


def main() -> int:
    errors = validate_all()
    if not errors:
        print("GraphAr schema validation: ok")
        return 0
    for error in errors:
        print(f"{error.path}: {error.message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
