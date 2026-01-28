import os
import re
from pathlib import Path

import pytest


def _has_google_imports(root: Path) -> list[str]:
    pattern = re.compile(r"^\s*(from|import)\s+google(\.|\s|$)")
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            if pattern.search(line):
                offenders.append(str(path))
                break
    return offenders


@pytest.mark.skipif(
    os.getenv("RETIKON_ALLOW_GCP_IMPORTS", "1") == "1",
    reason="Boundary enforcement disabled until Core decoupling is complete",
)
def test_core_has_no_google_imports() -> None:
    root = Path(__file__).resolve().parents[2] / "retikon_core"
    offenders = _has_google_imports(root)
    assert not offenders, "Found google imports in Core: " + ", ".join(offenders)
