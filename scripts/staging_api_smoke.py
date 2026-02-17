from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from scripts.firebase_token import (
    FirebaseTokenOptions,
    read_secret_via_gcloud,
    refresh_firebase_id_token,
)


DEFAULT_PROJECT = "simitor"
DEFAULT_REGION = "us-central1"
DEFAULT_ENV = "staging"
DEFAULT_QUERY_SERVICE = "retikon-query"
DEFAULT_FIREBASE_API_KEY_SECRET = "retikon-firebase-api-key"


def _run_json(cmd: list[str]) -> dict[str, Any]:
    raw = subprocess.check_output(cmd, text=True).strip()
    return json.loads(raw or "{}")


def _query_service_url(*, project: str, region: str, env: str, service: str) -> str:
    service_name = f"{service}-{env}"
    payload = _run_json(
        [
            "gcloud",
            "run",
            "services",
            "describe",
            service_name,
            "--project",
            project,
            "--region",
            region,
            "--format=json",
        ]
    )
    base = (payload.get("status") or {}).get("url")
    if not base:
        raise RuntimeError(f"Unable to resolve Cloud Run URL for {service_name}")
    return str(base).rstrip("/") + "/query"


def _load_image_base64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def _post_json(
    *,
    client: httpx.Client,
    url: str,
    auth_token: str,
    payload: dict[str, Any],
) -> tuple[int, dict[str, Any] | None]:
    try:
        response = client.post(
            url,
            headers={
                "Authorization": f"Bearer {auth_token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
    except httpx.HTTPError as exc:
        return 0, {"error": {"code": "HTTP_ERROR", "message": str(exc)}}
    data = None
    try:
        data = response.json()
    except Exception:
        data = None
    return response.status_code, data


@dataclass(frozen=True)
class CheckResult:
    check: str
    ok: bool
    status: int
    body: dict[str, Any] | None = None


def _has_typed_error_shape(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    err = payload.get("error")
    if not isinstance(err, dict):
        return False
    if not isinstance(err.get("code"), str):
        return False
    if not isinstance(err.get("message"), str):
        return False
    details = err.get("details")
    return details is None or isinstance(details, list)


def _why_has_modality(payload: dict[str, Any] | None, modality: str) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for item in results:
        if not isinstance(item, dict):
            continue
        why = item.get("why")
        if not isinstance(why, list):
            continue
        for entry in why:
            if isinstance(entry, dict) and entry.get("modality") == modality:
                return True
    return False


def _why_has_model(payload: dict[str, Any] | None, model: str) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for item in results:
        if not isinstance(item, dict):
            continue
        why = item.get("why")
        if not isinstance(why, list):
            continue
        for entry in why:
            if isinstance(entry, dict) and entry.get("model") == model:
                return True
    return False


def _has_video_moment(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    for item in results:
        if not isinstance(item, dict):
            continue
        if item.get("asset_type") != "video":
            continue
        if item.get("start_ms") is None or item.get("end_ms") is None:
            continue
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run staging query API smoke checks.")
    parser.add_argument("--project", default=os.getenv("GOOGLE_CLOUD_PROJECT", DEFAULT_PROJECT))
    parser.add_argument("--region", default=os.getenv("GOOGLE_CLOUD_REGION", DEFAULT_REGION))
    parser.add_argument("--env", default=DEFAULT_ENV)
    parser.add_argument("--service", default=DEFAULT_QUERY_SERVICE)
    parser.add_argument("--query-url", help="Override query URL (defaults to Cloud Run service URL).")
    parser.add_argument("--auth-token", help="Bearer token (optional if firebase secret is available).")
    parser.add_argument(
        "--firebase-api-key-secret",
        default=DEFAULT_FIREBASE_API_KEY_SECRET,
        help="Secret Manager secret name holding Firebase Web API key.",
    )
    parser.add_argument("--firebase-service-account", help="Service account email for custom token signing.")
    parser.add_argument(
        "--eval-image-path",
        help="Local image used for image query checks (defaults to tests/fixtures/eval/metadata.json run_id).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="HTTP client timeout seconds (should be >= Cloud Run request timeout).",
    )
    parser.add_argument("--output", help="Write JSON output to this path.")
    args = parser.parse_args()

    query_url = args.query_url or _query_service_url(
        project=args.project,
        region=args.region,
        env=args.env,
        service=args.service,
    )

    auth_token = args.auth_token or os.getenv("RETIKON_AUTH_TOKEN") or os.getenv("RETIKON_JWT")
    if not auth_token:
        api_key = read_secret_via_gcloud(project=args.project, secret=args.firebase_api_key_secret)
        if not api_key:
            raise SystemExit("Missing auth-token and unable to read Firebase API key secret.")
        auth_token = refresh_firebase_id_token(
            FirebaseTokenOptions(
                project=args.project,
                api_key=api_key,
                service_account_email=args.firebase_service_account,
            )
        )

    image_path = None
    if args.eval_image_path:
        image_path = Path(args.eval_image_path)
    else:
        try:
            metadata = json.loads(Path("tests/fixtures/eval/metadata.json").read_text(encoding="ascii"))
            run_id = str(metadata.get("run_id") or "").strip()
            if run_id:
                asset_dir = Path("tests/fixtures/eval/assets") / run_id
                # Prefer a frame extracted from the eval video so image queries exercise
                # keyframe retrieval (video moments + grouping). Fall back to the standalone
                # eval image if the frame isn't present.
                frame_path = asset_dir / f"{run_id}-video-frame.png"
                if frame_path.exists():
                    image_path = frame_path
                else:
                    image_path = asset_dir / f"{run_id}-image.png"
        except Exception:
            image_path = None
    if image_path is None:
        image_path = Path(
            "tests/fixtures/eval/assets/eval-20260214-164126/eval-20260214-164126-image.png"
        )
    image_base64 = None
    if image_path.exists():
        image_base64 = _load_image_base64(image_path)
    expect_video_keyframe = image_path.name.endswith("-video-frame.png")

    checks: list[CheckResult] = []

    with httpx.Client(timeout=args.timeout) as client:
        # Basic query + meta.
        status, body = _post_json(
            client=client,
            url=query_url,
            auth_token=auth_token,
            payload={"top_k": 5, "query_text": "Eval token", "page_limit": 2},
        )
        checks.append(CheckResult(check="basic_query_200", ok=status == 200, status=status))
        has_meta = isinstance(body, dict) and isinstance(body.get("meta"), dict)
        checks.append(CheckResult(check="response_has_meta", ok=has_meta, status=status))

        # Pagination cursor should exist when page_limit < result count.
        has_next = isinstance(body, dict) and bool(body.get("next_page_token"))
        checks.append(CheckResult(check="next_page_token_present", ok=has_next, status=status))

        # Grouping should be present when group_by=video is requested.
        status2, body2 = _post_json(
            client=client,
            url=query_url,
            auth_token=auth_token,
            payload={
                "top_k": 10,
                "query_text": "Eval token",
                "group_by": "video",
                "page_limit": 5,
            },
        )
        grouping_ok = status2 == 200 and isinstance(body2, dict) and "grouping" in body2
        checks.append(CheckResult(check="grouping_present", ok=grouping_ok, status=status2))

        # Typed error payload shape (invalid mode).
        status3, body3 = _post_json(
            client=client,
            url=query_url,
            auth_token=auth_token,
            payload={"top_k": 1, "query_text": "demo", "mode": "bogus"},
        )
        checks.append(
            CheckResult(
                check="typed_error_shape",
                ok=status3 == 400 and _has_typed_error_shape(body3),
                status=status3,
                body=body3 if status3 != 200 else None,
            )
        )

        # Image query contract check + v2 explainability (if eval image exists).
        if image_base64:
            status4, body4 = _post_json(
                client=client,
                url=query_url,
                auth_token=auth_token,
                payload={
                    "top_k": 10,
                    "image_base64": image_base64,
                    "mode": "image",
                    "page_limit": 5,
                    "group_by": "video",
                },
            )
            checks.append(CheckResult(check="image_query_200", ok=status4 == 200, status=status4))
            image_grouping_ok = status4 == 200 and isinstance(body4, dict) and "grouping" in body4
            checks.append(
                CheckResult(check="image_grouping_present", ok=image_grouping_ok, status=status4)
            )
            if expect_video_keyframe:
                checks.append(
                    CheckResult(
                        check="image_query_has_video_moment",
                        ok=status4 == 200 and _has_video_moment(body4),
                        status=status4,
                    )
                )
            checks.append(
                CheckResult(
                    check="why_has_vision_v2",
                    ok=status4 == 200 and _why_has_modality(body4, "vision_v2"),
                    status=status4,
                )
            )
            checks.append(
                CheckResult(
                    check="why_has_siglip2_model",
                    ok=status4 == 200
                    and _why_has_model(body4, "google/siglip2-base-patch16-224"),
                    status=status4,
                )
            )

    passed = sum(1 for item in checks if item.ok)
    summary = {
        "query_url": query_url,
        "total": len(checks),
        "passed": passed,
        "checks": [item.__dict__ for item in checks],
        "all_passed": passed == len(checks),
    }

    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="ascii")

    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
