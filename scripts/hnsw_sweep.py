#!/usr/bin/env python3
from __future__ import annotations

import argparse
import itertools
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def _update_run_job(job_name: str, project: str, region: str, env_vars: dict[str, str]) -> None:
    env_arg = ",".join(f"{key}={value}" for key, value in env_vars.items())
    _run(
        [
            "gcloud",
            "run",
            "jobs",
            "update",
            job_name,
            "--project",
            project,
            "--region",
            region,
            "--update-env-vars",
            env_arg,
        ]
    )


def _execute_job(job_name: str, project: str, region: str) -> None:
    _run(
        [
            "gcloud",
            "run",
            "jobs",
            "execute",
            job_name,
            "--project",
            project,
            "--region",
            region,
            "--wait",
        ]
    )


def _update_query_service(service_name: str, project: str, region: str, ef_search: int) -> None:
    _run(
        [
            "gcloud",
            "run",
            "services",
            "update",
            service_name,
            "--project",
            project,
            "--region",
            region,
            "--update-env-vars",
            f"HNSW_EF_SEARCH={ef_search}",
        ]
    )


def _refresh_firebase_token(
    *,
    api_key: str,
    project: str,
    service_account: str | None,
) -> str:
    service_account_email = service_account or f"firebase-adminsdk-fbsvc@{project}.iam.gserviceaccount.com"
    now = int(time.time())
    claims = {
        "iss": service_account_email,
        "sub": service_account_email,
        "aud": "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit",
        "iat": now,
        "exp": now + 3600,
        "uid": "retikon-eval",
        "claims": {
            "org_id": project,
            "roles": ["admin"],
            "groups": ["admins"],
            "email": f"retikon-eval@{project}.local",
        },
    }
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as payload_file:
        payload_file.write(json.dumps(claims, separators=(",", ":")).encode("ascii"))
        payload_path = payload_file.name
    with tempfile.NamedTemporaryFile(suffix=".signed", delete=False) as signed_file:
        signed_path = signed_file.name
    _run(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "sign-jwt",
            "--iam-account",
            service_account_email,
            "--project",
            project,
            payload_path,
            signed_path,
        ]
    )
    with open(signed_path, "r", encoding="ascii") as handle:
        signed_jwt = handle.read().strip()
    request = urllib.request.Request(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={api_key}",
        data=json.dumps({"token": signed_jwt, "returnSecureToken": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("idToken")
    if not token:
        raise RuntimeError(f"Failed to refresh Firebase token: {payload}")
    return token


def _run_eval(eval_file: str, query_url: str, auth_token: str, output_path: Path, eval_run_id: str) -> dict:
    cmd = [
        sys.executable,
        "scripts/run_retrieval_eval.py",
        "--eval-file",
        eval_file,
        "--query-url",
        query_url,
        "--auth-token",
        auth_token,
        "--output",
        str(output_path),
        "--eval-run-id",
        eval_run_id,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run HNSW parameter sweep.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--region", default="us-central1")
    parser.add_argument("--env", default="staging")
    parser.add_argument("--index-job", help="Cloud Run job name")
    parser.add_argument("--query-service", help="Cloud Run query service name")
    parser.add_argument("--eval-file", required=True)
    parser.add_argument("--query-url", required=True)
    parser.add_argument("--auth-token", help="Static auth token (optional if firebase api key is provided).")
    parser.add_argument("--firebase-api-key", help="Firebase Web API key for token refresh.")
    parser.add_argument("--firebase-service-account", help="Service account email to sign Firebase custom tokens.")
    parser.add_argument("--ef-construction", default="100,150,200,300")
    parser.add_argument("--m-values", default="8,12,16,24")
    parser.add_argument("--ef-search", default="32,64,96,128")
    parser.add_argument("--output", default="tests/fixtures/eval/hnsw_sweep.json")
    parser.add_argument("--sleep-seconds", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    job_name = args.index_job or f"retikon-index-builder-{args.env}"
    query_service = args.query_service or f"retikon-query-{args.env}"
    if not args.auth_token and not args.firebase_api_key and not args.dry_run:
        raise SystemExit("--auth-token or --firebase-api-key is required")

    ef_construction = [int(item) for item in args.ef_construction.split(",") if item.strip()]
    m_values = [int(item) for item in args.m_values.split(",") if item.strip()]
    ef_search_values = [int(item) for item in args.ef_search.split(",") if item.strip()]

    results: list[dict] = []
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    for ef_search in ef_search_values:
        if not args.dry_run:
            _update_query_service(query_service, args.project, args.region, ef_search)
            time.sleep(args.sleep_seconds)
        for ef, m_val in itertools.product(ef_construction, m_values):
            run_id = f"hnsw-{ef}-m{m_val}-efs{ef_search}-{int(time.time())}"
            if args.dry_run:
                print(
                    f"[dry-run] job={job_name} ef={ef} m={m_val} ef_search={ef_search} eval_run_id={run_id}"
                )
                continue
            _update_run_job(
                job_name,
                args.project,
                args.region,
                {
                    "HNSW_EF_CONSTRUCTION": str(ef),
                    "HNSW_M": str(m_val),
                    "INDEX_BUILDER_INCREMENTAL": "0",
                    "INDEX_BUILDER_SKIP_IF_UNCHANGED": "0",
                },
            )
            _execute_job(job_name, args.project, args.region)
            time.sleep(args.sleep_seconds)
            auth_token = args.auth_token
            if args.firebase_api_key:
                auth_token = _refresh_firebase_token(
                    api_key=args.firebase_api_key,
                    project=args.project,
                    service_account=args.firebase_service_account,
                )
            if not auth_token:
                raise SystemExit("Missing auth token for eval run.")
            eval_output = output_path.parent / f"{run_id}.json"
            summary = _run_eval(
                args.eval_file,
                args.query_url,
                auth_token,
                eval_output,
                run_id,
            )
            summary["hnsw_ef_construction"] = ef
            summary["hnsw_m"] = m_val
            summary["hnsw_ef_search"] = ef_search
            results.append(summary)
            output_path.write_text(
                json.dumps(results, indent=2, sort_keys=True), encoding="ascii"
            )

    if args.dry_run:
        return 0

    output_path.write_text(json.dumps(results, indent=2, sort_keys=True), encoding="ascii")
    print(f"Wrote sweep results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
