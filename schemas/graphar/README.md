# GraphAr Schema YAMLs

This folder defines the proposed GraphAr schema metadata for Retikon. Each
entity has a `prefix.yml` describing the logical schema and the physical file
layout under `retikon_v2/`.

## YAML structure

Common fields:

- `version`: integer schema version
- `name`: entity name
- `entity`: `vertex` or `edge`
- `path_prefix`: relative path under `retikon_v2/`
- `files`: mapping of logical files to physical paths
- `primary_key`: (vertices only) primary ID field
- `directed`: (edges only) whether the edge is directed
- `fields`: list of column definitions

Field definitions:

- `name`: column name
- `type`: `string`, `int32`, `int64`, `timestamp`, or `list<float32>`
- `nullable`: `true` or `false`
- `file`: optional; `text` or `vector` to map to non-core files
- `vector_length`: required for `list<float32>` vectors

## Notes

- All IDs are UUIDv4 strings.
- The `files` mapping must match the on-disk layout:
  - vertices: `vertices/<Type>/{core,text,vector}`
  - edges: `edges/<Type>/adj_list`
- Column order should be deterministic and match the `fields` order.
- Schema changes must be additive-only.
