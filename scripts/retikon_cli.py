from __future__ import annotations

from importlib import util
from pathlib import Path


def _load_cli_module():
    cli_path = Path(__file__).resolve().parents[1] / "retikon_cli" / "cli.py"
    spec = util.spec_from_file_location("retikon_cli_cli_fallback", cli_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load CLI module from {cli_path}")
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from retikon_cli import cli as _cli_module
except Exception:
    _cli_module = _load_cli_module()

cli = _cli_module
main = _cli_module.main

if __name__ == "__main__":
    raise SystemExit(main())
