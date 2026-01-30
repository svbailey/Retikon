from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> str:
    return subprocess.check_output(cmd, text=True).strip()


def _resolve_dashboard(
    project: str,
    dashboard: str | None,
    display_name: str | None,
) -> str:
    if dashboard:
        return dashboard
    if not display_name:
        raise ValueError("Provide --dashboard or --display-name")
    output = _run(
        [
            "gcloud",
            "monitoring",
            "dashboards",
            "list",
            "--project",
            project,
            "--format=json",
        ]
    )
    dashboards = json.loads(output or "[]")
    matches = [
        item["name"]
        for item in dashboards
        if item.get("displayName") == display_name and "name" in item
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one dashboard named '{display_name}', found {len(matches)}"
        )
    return matches[0]


def _export_dashboard(project: str, dashboard: str, output_path: Path) -> None:
    raw = _run(
        [
            "gcloud",
            "monitoring",
            "dashboards",
            "describe",
            dashboard,
            "--project",
            project,
            "--format=json",
        ]
    )
    payload = json.loads(raw)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _apply_dashboard(project: str, dashboard: str, input_path: Path) -> None:
    _run(
        [
            "gcloud",
            "monitoring",
            "dashboards",
            "update",
            dashboard,
            "--project",
            project,
            "--config-from-file",
            str(input_path),
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync Retikon monitoring dashboard.")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", ""))
    parser.add_argument("--dashboard")
    parser.add_argument("--display-name")
    parser.add_argument(
        "--output",
        default="infrastructure/monitoring/ops_dashboard.json",
    )
    parser.add_argument("--export", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    if not args.project:
        raise SystemExit("Missing --project or GOOGLE_CLOUD_PROJECT")

    if not args.export and not args.apply:
        args.export = True

    dashboard = _resolve_dashboard(args.project, args.dashboard, args.display_name)
    output_path = Path(args.output)

    if args.export:
        _export_dashboard(args.project, dashboard, output_path)
        print(f"Exported dashboard to {output_path}")

    if args.apply:
        _apply_dashboard(args.project, dashboard, output_path)
        print(f"Applied dashboard from {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
