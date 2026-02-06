from __future__ import annotations

import os
from datetime import timedelta
from urllib.parse import urlparse

import google.auth
from google.auth import iam
from google.auth.transport.requests import Request
from google.cloud import storage
from google.oauth2 import service_account

from retikon_core.errors import RecoverableError

_SIGNER_CREDS = None
_SIGNER_CLIENT = None


def _get_signing_credentials():
    global _SIGNER_CREDS
    if _SIGNER_CREDS is not None:
        return _SIGNER_CREDS
    creds, _ = google.auth.default()
    scopes = [
        "https://www.googleapis.com/auth/devstorage.read_only",
        "https://www.googleapis.com/auth/iam",
    ]
    if hasattr(creds, "with_scopes"):
        creds = creds.with_scopes(scopes)
    if hasattr(creds, "sign_bytes"):
        _SIGNER_CREDS = creds
        return _SIGNER_CREDS
    request = Request()
    env_service_account = os.getenv("GOOGLE_SERVICE_ACCOUNT_EMAIL")
    service_account_email = env_service_account or getattr(
        creds, "service_account_email", None
    )
    if service_account_email == "default" and env_service_account:
        service_account_email = env_service_account
    if not service_account_email:
        raise RecoverableError(
            "Service account email is required to sign URLs via IAM."
        )
    signer = iam.Signer(request, creds, service_account_email)
    _SIGNER_CREDS = service_account.Credentials(
        signer=signer,
        service_account_email=service_account_email,
        token_uri="https://oauth2.googleapis.com/token",
    )
    return _SIGNER_CREDS


def _get_storage_client() -> storage.Client:
    global _SIGNER_CLIENT
    if _SIGNER_CLIENT is not None:
        return _SIGNER_CLIENT
    creds = _get_signing_credentials()
    _SIGNER_CLIENT = storage.Client(credentials=creds)
    return _SIGNER_CLIENT


def sign_gcs_uri(uri: str) -> str:
    if not uri.startswith("gs://"):
        return uri
    parsed = urlparse(uri)
    bucket_name = parsed.netloc
    blob_name = parsed.path.lstrip("/")
    if not bucket_name or not blob_name:
        raise RecoverableError(f"Invalid GCS URI for signing: {uri}")
    client = _get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    expiration = int(os.getenv("RETIKON_DUCKDB_SIGNED_URL_TTL_SEC", "900"))
    try:
        return blob.generate_signed_url(
            version="v4",
            expiration=timedelta(seconds=expiration),
            method="GET",
            credentials=_get_signing_credentials(),
        )
    except Exception as exc:
        raise RecoverableError(f"Failed to sign GCS URI: {uri}: {exc}") from exc
