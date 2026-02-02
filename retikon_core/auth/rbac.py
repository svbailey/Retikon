from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Iterable

import fsspec

from retikon_core.auth.types import AuthContext
from retikon_core.storage.paths import join_uri

ACTION_QUERY = "query:read"
ACTION_INGEST = "ingest:write"


@dataclass(frozen=True)
class Role:
    name: str
    permissions: tuple[str, ...]


DEFAULT_ROLES: dict[str, Role] = {
    "admin": Role("admin", ("*",)),
    "reader": Role("reader", (ACTION_QUERY,)),
    "ingestor": Role("ingestor", (ACTION_INGEST,)),
    "operator": Role("operator", (ACTION_QUERY, ACTION_INGEST)),
}


def _bindings_uri(base_uri: str) -> str:
    override = os.getenv("RBAC_BINDINGS_URI")
    if override:
        return override
    return join_uri(base_uri, "control", "rbac_bindings.json")


def load_role_bindings(base_uri: str) -> dict[str, list[str]]:
    uri = _bindings_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return {}
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("bindings", []) if isinstance(payload, dict) else []
    bindings: dict[str, list[str]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        api_key_id = str(item.get("principal_id") or item.get("api_key_id") or "")
        roles = item.get("roles", [])
        if not api_key_id or not isinstance(roles, list):
            continue
        bindings[api_key_id] = [str(role) for role in roles if role]
    return bindings


def _default_role() -> str | None:
    value = os.getenv("RBAC_DEFAULT_ROLE", "reader").strip()
    return value or None


def _permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role_name in roles:
        role = DEFAULT_ROLES.get(role_name)
        if role:
            permissions.update(role.permissions)
    return permissions


def is_action_allowed(
    auth_context: AuthContext | None,
    action: str,
    base_uri: str,
) -> bool:
    if auth_context is None:
        return False
    if auth_context.is_admin:
        return True

    roles: list[str] | None = None
    if auth_context.roles:
        roles = list(auth_context.roles)
    if not roles:
        bindings = load_role_bindings(base_uri)
        roles = bindings.get(auth_context.api_key_id)
        if not roles:
            default_role = _default_role()
            roles = [default_role] if default_role else []

    permissions = _permissions_for_roles(roles)
    if "*" in permissions:
        return True
    return action in permissions
