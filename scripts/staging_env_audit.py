from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path
from typing import Any


DEFAULT_PROJECT = "simitor"
DEFAULT_REGION = "us-central1"
DEFAULT_ENV = "staging"
DEFAULT_QUERY_SERVICE = "retikon-query"


def _run_json(cmd: list[str]) -> dict[str, Any]:
    raw = subprocess.check_output(cmd, text=True).strip()
    return json.loads(raw or "{}")


def _extract_env(payload: dict[str, Any]) -> dict[str, str]:
    template = (
        (payload.get("spec") or {})
        .get("template", {})
        .get("spec", {})
    )
    containers = template.get("containers") or []
    if not containers:
        return {}
    env_list = (containers[0] or {}).get("env") or []
    env: dict[str, str] = {}
    for item in env_list:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        value = item.get("value")
        if not isinstance(name, str):
            continue
        if value is None:
            continue
        env[name] = str(value)
    return env


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit Cloud Run query env vars for staging gates.")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT))
    parser.add_argument("--region", default=os.getenv("GOOGLE_CLOUD_REGION", DEFAULT_REGION))
    parser.add_argument("--env", default=DEFAULT_ENV)
    parser.add_argument("--service", default=DEFAULT_QUERY_SERVICE)
    parser.add_argument(
        "--required",
        default="RERANK_ENABLED,SEARCH_GROUP_BY_ENABLED,SEARCH_PAGINATION_ENABLED,SEARCH_TYPED_ERRORS_ENABLED,SEARCH_WHY_ENABLED,QUERY_FUSION_RRF_K,QUERY_FUSION_WEIGHT_VERSION,VISION_V2_ENABLED,VISION_V2_MODEL_NAME,VISION_V2_EMBED_BACKEND,VISION_V2_TIMEOUT_S,MODEL_INFERENCE_VISION_V2_TIMEOUT_S",
        help="Comma-separated required env var keys to check.",
    )
    parser.add_argument("--output", help="Write JSON output to this path.")
    args = parser.parse_args()

    service_name = f"{args.service}-{args.env}"
    payload = _run_json(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service_name,
            "--project",
            args.project,
            "--region",
            args.region,
            "--format=json",
        ]
    )
    env = _extract_env(payload)

    required = [item.strip() for item in args.required.split(",") if item.strip()]
    present: dict[str, str] = {}
    missing: list[str] = []
    for key in required:
        if key in env and env[key] != "":
            present[key] = env[key]
        else:
            missing.append(key)

    summary = {"missing": missing, "present": present, "optional_present": {}}
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())

