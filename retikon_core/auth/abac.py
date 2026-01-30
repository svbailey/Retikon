from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any

import fsspec

from retikon_core.auth.types import AuthContext
from retikon_core.storage.paths import join_uri


def _policies_uri(base_uri: str) -> str:
    override = os.getenv("ABAC_POLICY_URI")
    if override:
        return override
    return join_uri(base_uri, "control", "abac_policies.json")


@dataclass(frozen=True)
class Policy:
    id: str
    effect: str
    conditions: dict[str, Any]


def load_policies(base_uri: str) -> list[Policy]:
    uri = _policies_uri(base_uri)
    fs, path = fsspec.core.url_to_fs(uri)
    if not fs.exists(path):
        return []
    with fs.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    items = payload.get("policies", []) if isinstance(payload, dict) else []
    results: list[Policy] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        results.append(
            Policy(
                id=str(item.get("id", "")),
                effect=str(item.get("effect", "allow")),
                conditions=_coerce_dict(item.get("conditions")),
            )
        )
    return results


def build_attributes(auth_context: AuthContext | None, action: str) -> dict[str, Any]:
    attrs: dict[str, Any] = {"action": action}
    if not auth_context:
        return attrs
    attrs["api_key_id"] = auth_context.api_key_id
    attrs["actor_type"] = auth_context.actor_type
    attrs["actor_id"] = auth_context.actor_id or auth_context.api_key_id
    if auth_context.email:
        attrs["email"] = auth_context.email
    if auth_context.roles:
        attrs["roles"] = list(auth_context.roles)
    if auth_context.groups:
        attrs["groups"] = list(auth_context.groups)
    if auth_context.scope:
        attrs["org_id"] = auth_context.scope.org_id
        attrs["site_id"] = auth_context.scope.site_id
        attrs["stream_id"] = auth_context.scope.stream_id
    return attrs


def is_allowed(
    auth_context: AuthContext | None,
    action: str,
    base_uri: str,
) -> bool:
    policies = load_policies(base_uri)
    default_allow = os.getenv("ABAC_DEFAULT_ALLOW", "1") == "1"
    if not policies:
        return default_allow
    attrs = build_attributes(auth_context, action)
    return evaluate_policies(policies, attrs, default_allow=default_allow)


def abac_allowed(
    auth_context: AuthContext | None,
    action: str,
    base_uri: str,
) -> bool:
    return is_allowed(auth_context, action, base_uri)


def evaluate_policies(
    policies: list[Policy],
    attrs: dict[str, Any],
    *,
    default_allow: bool,
) -> bool:
    matched_allow = False
    for policy in policies:
        if not _matches(policy.conditions, attrs):
            continue
        effect = policy.effect.lower()
        if effect == "deny":
            return False
        if effect == "allow":
            matched_allow = True
    if matched_allow:
        return True
    return default_allow


def _matches(conditions: dict[str, Any], attrs: dict[str, Any]) -> bool:
    if not conditions:
        return True
    for key, expected in conditions.items():
        actual = attrs.get(key)
        if not _match_value(actual, expected):
            return False
    return True


def _match_value(actual: Any, expected: Any) -> bool:
    if isinstance(expected, (list, tuple, set)):
        return actual in expected
    return actual == expected


def _coerce_dict(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}
