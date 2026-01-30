from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from gcp_adapter.ingestion_service import app as ingest_app
from gcp_adapter.query_service import app as query_app


def _make_token(
    *,
    secret: str,
    issuer: str,
    audience: str,
    subject: str = "user-1",
    roles: list[str] | None = None,
    org_id: str | None = "org-1",
) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": subject,
        "iss": issuer,
        "aud": audience,
        "exp": int((now + timedelta(minutes=5)).timestamp()),
        "iat": int(now.timestamp()),
        "email": "user@example.com",
        "roles": roles or ["reader"],
        "org_id": org_id,
    }
    return jwt.encode(claims, secret, algorithm="HS256")


def _jwt_env(monkeypatch, *, secret: str, issuer: str, audience: str) -> None:
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("AUTH_JWT_HS256_SECRET", secret)
    monkeypatch.setenv("AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.setenv("AUTH_ISSUER", issuer)
    monkeypatch.setenv("AUTH_AUDIENCE", audience)


def test_query_accepts_jwt(monkeypatch):
    secret = "secret"
    issuer = "https://issuer.example"
    audience = "retikon"
    _jwt_env(monkeypatch, secret=secret, issuer=issuer, audience=audience)

    token = _make_token(secret=secret, issuer=issuer, audience=audience)
    client = TestClient(query_app)
    resp = client.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200


def test_jwt_rbac_enforced_for_ingest(monkeypatch):
    secret = "secret"
    issuer = "https://issuer.example"
    audience = "retikon"
    _jwt_env(monkeypatch, secret=secret, issuer=issuer, audience=audience)
    monkeypatch.setenv("RBAC_ENFORCE", "1")

    token = _make_token(
        secret=secret,
        issuer=issuer,
        audience=audience,
        roles=["reader"],
    )
    client_query = TestClient(query_app)
    resp = client_query.post(
        "/query",
        json={"query_text": "hello"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    client_ingest = TestClient(ingest_app)
    resp = client_ingest.post(
        "/ingest",
        json={"specversion": "1.0", "data": {}},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
