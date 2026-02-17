from __future__ import annotations

import json
import subprocess
import tempfile
import time
import urllib.request
from dataclasses import dataclass


@dataclass(frozen=True)
class FirebaseTokenOptions:
    project: str
    api_key: str
    service_account_email: str | None = None
    uid: str = "retikon-eval"
    email: str | None = None


def read_secret_via_gcloud(*, project: str, secret: str) -> str:
    value = subprocess.check_output(
        [
            "gcloud",
            "secrets",
            "versions",
            "access",
            "latest",
            "--project",
            project,
            "--secret",
            secret,
        ],
        text=True,
    )
    return (value or "").strip()


def refresh_firebase_id_token(options: FirebaseTokenOptions) -> str:
    service_account_email = (
        options.service_account_email
        or f"firebase-adminsdk-fbsvc@{options.project}.iam.gserviceaccount.com"
    )
    now = int(time.time())
    claims = {
        "iss": service_account_email,
        "sub": service_account_email,
        "aud": "https://identitytoolkit.googleapis.com/google.identity.identitytoolkit.v1.IdentityToolkit",
        "iat": now,
        "exp": now + 3600,
        "uid": options.uid,
        "claims": {
            "org_id": options.project,
            "roles": ["admin"],
            "groups": ["admins"],
            "email": options.email or f"{options.uid}@{options.project}.local",
        },
    }

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as payload_file:
        payload_file.write(json.dumps(claims, separators=(",", ":")).encode("ascii"))
        payload_path = payload_file.name
    with tempfile.NamedTemporaryFile(suffix=".signed", delete=False) as signed_file:
        signed_path = signed_file.name

    # Use gcloud for signing, but keep stdout/stderr quiet to avoid polluting
    # callers that capture stdout (e.g., CI command substitution).
    subprocess.run(
        [
            "gcloud",
            "iam",
            "service-accounts",
            "sign-jwt",
            "--iam-account",
            service_account_email,
            "--project",
            options.project,
            payload_path,
            signed_path,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    with open(signed_path, "r", encoding="ascii") as handle:
        signed_jwt = handle.read().strip()

    request = urllib.request.Request(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key={options.api_key}",
        data=json.dumps({"token": signed_jwt, "returnSecureToken": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    token = payload.get("idToken")
    if not token:
        raise RuntimeError(f"Failed to refresh Firebase token: {payload}")
    return str(token)

