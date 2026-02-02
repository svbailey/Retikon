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

ACTION_PRIVACY_POLICY_LIST = "privacy.policy.list"
ACTION_PRIVACY_POLICY_CREATE = "privacy.policy.create"
ACTION_PRIVACY_POLICY_UPDATE = "privacy.policy.update"

ACTION_FLEET_DEVICE_LIST = "fleet.device.list"
ACTION_FLEET_DEVICE_CREATE = "fleet.device.create"
ACTION_FLEET_DEVICE_STATUS_UPDATE = "fleet.device.status.update"
ACTION_FLEET_ROLLOUT_PLAN = "fleet.rollout.plan"
ACTION_FLEET_ROLLOUT_ROLLBACK = "fleet.rollout.rollback"
ACTION_FLEET_SECURITY_CHECK = "fleet.security.check"

ACTION_WORKFLOWS_LIST = "workflows.list"
ACTION_WORKFLOWS_CREATE = "workflows.create"
ACTION_WORKFLOWS_UPDATE = "workflows.update"
ACTION_WORKFLOWS_RUNS_LIST = "workflows.runs.list"
ACTION_WORKFLOWS_SCHEDULE_TICK = "workflows.schedule.tick"
ACTION_WORKFLOWS_RUN_CREATE = "workflows.run.create"

ACTION_CHAOS_POLICY_LIST = "chaos.policy.list"
ACTION_CHAOS_POLICY_CREATE = "chaos.policy.create"
ACTION_CHAOS_POLICY_UPDATE = "chaos.policy.update"
ACTION_CHAOS_RUN_LIST = "chaos.run.list"
ACTION_CHAOS_RUN_CREATE = "chaos.run.create"
ACTION_CHAOS_CONFIG_READ = "chaos.config.read"

ACTION_DATASET_LIST = "data_factory.dataset.list"
ACTION_DATASET_CREATE = "data_factory.dataset.create"
ACTION_ANNOTATION_LIST = "data_factory.annotation.list"
ACTION_ANNOTATION_CREATE = "data_factory.annotation.create"
ACTION_MODEL_LIST = "data_factory.model.list"
ACTION_MODEL_CREATE = "data_factory.model.create"
ACTION_TRAINING_CREATE = "data_factory.training.create"
ACTION_TRAINING_LIST = "data_factory.training.list"
ACTION_TRAINING_READ = "data_factory.training.read"
ACTION_CONNECTORS_LIST = "data_factory.connectors.list"
ACTION_OCR_CONNECTOR_CREATE = "data_factory.ocr_connector.create"
ACTION_OCR_CONNECTOR_LIST = "data_factory.ocr_connector.list"
ACTION_OFFICE_CONVERSION_CREATE = "data_factory.office_conversion.create"
ACTION_OFFICE_CONVERSION_READ = "data_factory.office_conversion.read"

ACTION_WEBHOOKS_LIST = "webhooks.list"
ACTION_WEBHOOKS_CREATE = "webhooks.create"
ACTION_ALERTS_LIST = "alerts.list"
ACTION_ALERTS_CREATE = "alerts.create"
ACTION_EVENTS_DISPATCH = "events.dispatch"

ACTION_AUDIT_LOGS_READ = "audit.logs.read"
ACTION_AUDIT_EXPORT = "audit.export"
ACTION_ACCESS_EXPORT = "access.export"

ACTION_DEV_UPLOAD = "dev.upload.create"
ACTION_DEV_INGEST_STATUS = "dev.ingest_status.read"
ACTION_DEV_MANIFEST = "dev.manifest.read"
ACTION_DEV_PARQUET_PREVIEW = "dev.parquet_preview.read"
ACTION_DEV_OBJECT = "dev.object.read"
ACTION_DEV_GRAPH_OBJECT = "dev.graph_object.read"
ACTION_DEV_SNAPSHOT_STATUS = "dev.snapshot_status.read"
ACTION_DEV_INDEX_BUILD = "dev.index_build.create"
ACTION_DEV_SNAPSHOT_RELOAD = "dev.snapshot_reload.create"
ACTION_DEV_INDEX_STATUS = "dev.index_status.read"

ACTION_EDGE_CONFIG_READ = "edge.config.read"
ACTION_EDGE_CONFIG_UPDATE = "edge.config.update"
ACTION_EDGE_BUFFER_STATUS = "edge.buffer.status"
ACTION_EDGE_BUFFER_REPLAY = "edge.buffer.replay"
ACTION_EDGE_BUFFER_PRUNE = "edge.buffer.prune"
ACTION_EDGE_UPLOAD = "edge.upload"


@dataclass(frozen=True)
class Role:
    name: str
    permissions: tuple[str, ...]


CONTROL_PLANE_READ_ACTIONS = (
    ACTION_PRIVACY_POLICY_LIST,
    ACTION_FLEET_DEVICE_LIST,
    ACTION_WORKFLOWS_LIST,
    ACTION_WORKFLOWS_RUNS_LIST,
    ACTION_CHAOS_POLICY_LIST,
    ACTION_CHAOS_RUN_LIST,
    ACTION_CHAOS_CONFIG_READ,
    ACTION_DATASET_LIST,
    ACTION_ANNOTATION_LIST,
    ACTION_MODEL_LIST,
    ACTION_TRAINING_LIST,
    ACTION_TRAINING_READ,
    ACTION_CONNECTORS_LIST,
    ACTION_OCR_CONNECTOR_LIST,
    ACTION_WEBHOOKS_LIST,
    ACTION_ALERTS_LIST,
)

CONTROL_PLANE_WRITE_ACTIONS = (
    ACTION_PRIVACY_POLICY_CREATE,
    ACTION_PRIVACY_POLICY_UPDATE,
    ACTION_FLEET_DEVICE_CREATE,
    ACTION_FLEET_DEVICE_STATUS_UPDATE,
    ACTION_FLEET_ROLLOUT_PLAN,
    ACTION_FLEET_ROLLOUT_ROLLBACK,
    ACTION_FLEET_SECURITY_CHECK,
    ACTION_WORKFLOWS_CREATE,
    ACTION_WORKFLOWS_UPDATE,
    ACTION_WORKFLOWS_SCHEDULE_TICK,
    ACTION_WORKFLOWS_RUN_CREATE,
    ACTION_CHAOS_POLICY_CREATE,
    ACTION_CHAOS_POLICY_UPDATE,
    ACTION_CHAOS_RUN_CREATE,
    ACTION_DATASET_CREATE,
    ACTION_ANNOTATION_CREATE,
    ACTION_MODEL_CREATE,
    ACTION_TRAINING_CREATE,
    ACTION_OCR_CONNECTOR_CREATE,
    ACTION_OFFICE_CONVERSION_CREATE,
    ACTION_OFFICE_CONVERSION_READ,
    ACTION_WEBHOOKS_CREATE,
    ACTION_ALERTS_CREATE,
    ACTION_EVENTS_DISPATCH,
    ACTION_AUDIT_LOGS_READ,
    ACTION_AUDIT_EXPORT,
    ACTION_ACCESS_EXPORT,
    ACTION_DEV_UPLOAD,
    ACTION_DEV_INGEST_STATUS,
    ACTION_DEV_MANIFEST,
    ACTION_DEV_PARQUET_PREVIEW,
    ACTION_DEV_OBJECT,
    ACTION_DEV_GRAPH_OBJECT,
    ACTION_DEV_SNAPSHOT_STATUS,
    ACTION_DEV_INDEX_BUILD,
    ACTION_DEV_SNAPSHOT_RELOAD,
    ACTION_DEV_INDEX_STATUS,
    ACTION_EDGE_CONFIG_READ,
    ACTION_EDGE_CONFIG_UPDATE,
    ACTION_EDGE_BUFFER_STATUS,
    ACTION_EDGE_BUFFER_REPLAY,
    ACTION_EDGE_BUFFER_PRUNE,
    ACTION_EDGE_UPLOAD,
)

DEFAULT_ROLES: dict[str, Role] = {
    "admin": Role("admin", ("*",)),
    "reader": Role("reader", (ACTION_QUERY,) + CONTROL_PLANE_READ_ACTIONS),
    "ingestor": Role("ingestor", (ACTION_INGEST, ACTION_EDGE_UPLOAD)),
    "operator": Role(
        "operator",
        (ACTION_QUERY, ACTION_INGEST)
        + CONTROL_PLANE_READ_ACTIONS
        + CONTROL_PLANE_WRITE_ACTIONS,
    ),
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
