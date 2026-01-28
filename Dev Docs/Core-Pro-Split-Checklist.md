# Core/Pro Split Checklist (Phase 7)

This checklist is used when splitting Core into a public OSS repo and Pro into
private code.

## Prepare
- [ ] Finalize Core/Pro boundary doc: `Dev Docs/Core-Pro-Boundary.md`.
- [ ] Ensure CI enforces no GCP imports in Core.
- [ ] Ensure all Pro-only docs live in `Dev Docs/pro/`.
- [ ] Confirm Core tests run with `requirements-core.txt` only.

## Core extraction (new public repo)
- [ ] Use `git filter-repo` to extract:
  - `retikon_core/`
  - `local_adapter/`
  - `retikon_cli/`
  - `sdk/`
  - `frontend/dev-console/`
  - `tests/core/`
  - `Dev Docs/Local-Development.md`
  - `Dev Docs/Core-Repo-Map.md`
  - `Dev Docs/Core-Pro-Boundary.md`
- [ ] Add OSS README + license + contribution guide.
- [ ] Publish to PyPI as `retikon-core`.

## Pro repo cleanup
- [ ] Remove Core code from Pro repo (replace with dependency).
- [ ] Pin Core version in Pro (PyPI or git submodule).
- [ ] Ensure Pro CI installs Core from PyPI.

## Release
- [ ] Tag Core repo release.
- [ ] Update Pro deployment docs to reference pinned Core version.
