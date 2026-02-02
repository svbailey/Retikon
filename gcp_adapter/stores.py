from __future__ import annotations

import logging
import os
from typing import Iterable

from retikon_core.auth import abac as abac_rules
from retikon_core.auth import rbac as rbac_rules
from retikon_core.auth.types import AuthContext
from retikon_core.stores import StoreBundle
from retikon_core.stores.interfaces import (
    AbacStore,
    ApiKeyStore,
    ConnectorStore,
    DataFactoryStore,
    FleetStore,
    PrivacyStore,
    RbacStore,
    WorkflowStore,
)
from retikon_core.stores.registry import get_store_bundle as core_get_store_bundle
from retikon_core.workflows.types import WorkflowRun, WorkflowSpec
from retikon_gcp.stores import get_store_bundle as gcp_get_store_bundle

_STORE_BUNDLE: StoreBundle | None = None
_STORE_KEY: tuple[object, ...] | None = None

logger = logging.getLogger(__name__)


def _read_mode() -> str:
    return os.getenv("CONTROL_PLANE_READ_MODE", "primary").strip().lower()


def _write_mode() -> str:
    return os.getenv("CONTROL_PLANE_WRITE_MODE", "single").strip().lower()


def _fallback_on_empty() -> bool:
    raw = os.getenv("CONTROL_PLANE_FALLBACK_ON_EMPTY")
    if raw is None:
        return _read_mode() == "fallback"
    return raw.strip() == "1"


def _fallback_backend(primary_backend: str) -> str:
    override = os.getenv("CONTROL_PLANE_FALLBACK_STORE")
    if override:
        return override.strip().lower()
    return "json" if primary_backend == "firestore" else "firestore"


def _is_empty(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set, dict)) and not value:
        return True
    return False


def _value_size(value: object) -> int | None:
    if value is None:
        return 0
    if isinstance(value, (list, tuple, set, dict)):
        return len(value)
    return None


def _read_with_fallback(
    *,
    primary_fn,
    secondary_fn,
    fallback_on_empty: bool,
    label: str,
):
    primary_backend = os.getenv("CONTROL_PLANE_STORE", "json").strip().lower()
    secondary_backend = _fallback_backend(primary_backend)
    try:
        result = primary_fn()
    except Exception as exc:
        if _read_mode() != "fallback":
            raise
        logger.warning(
            "Primary control-plane read failed; falling back",
            extra={
                "error_message": str(exc),
                "control_plane_op": label,
                "control_plane_primary": primary_backend,
                "control_plane_secondary": secondary_backend,
            },
        )
        fallback_result = secondary_fn()
        logger.warning(
            "Control-plane fallback used",
            extra={
                "control_plane_op": label,
                "control_plane_primary": primary_backend,
                "control_plane_secondary": secondary_backend,
                "control_plane_reason": "error",
            },
        )
        return fallback_result
    if fallback_on_empty and _is_empty(result):
        fallback_result = secondary_fn()
        secondary_empty = _is_empty(fallback_result)
        primary_size = _value_size(result)
        secondary_size = _value_size(fallback_result)
        if not secondary_empty:
            logger.warning(
                "Control-plane fallback used",
                extra={
                    "control_plane_op": label,
                    "control_plane_primary": primary_backend,
                    "control_plane_secondary": secondary_backend,
                    "control_plane_reason": "empty_primary",
                    "control_plane_primary_empty": True,
                    "control_plane_secondary_empty": secondary_empty,
                    "control_plane_primary_size": primary_size,
                    "control_plane_secondary_size": secondary_size,
                    "control_plane_mismatch": True,
                },
            )
        return fallback_result
    return result


def _write_dual(primary_fn, secondary_fn):
    result = primary_fn()
    if _write_mode() == "dual":
        try:
            secondary_fn()
        except Exception as exc:
            logger.warning(
                "Secondary control-plane write failed",
                extra={"error_message": str(exc)},
            )
    return result


def _upsert_by_id(load_fn, save_fn, item) -> None:
    items = list(load_fn() or [])
    updated = []
    found = False
    item_id = getattr(item, "id", None)
    for existing in items:
        if getattr(existing, "id", None) == item_id:
            updated.append(item)
            found = True
        else:
            updated.append(existing)
    if not found:
        updated.append(item)
    save_fn(updated)


class _DualRbacStore(RbacStore):
    def __init__(self, primary: RbacStore, secondary: RbacStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_role_bindings(self) -> dict[str, list[str]]:
        return _read_with_fallback(
            primary_fn=self._primary.load_role_bindings,
            secondary_fn=self._secondary.load_role_bindings,
            fallback_on_empty=_fallback_on_empty(),
            label="rbac.load_role_bindings",
        )

    def save_role_bindings(self, bindings: dict[str, list[str]]) -> str:
        return _write_dual(
            lambda: self._primary.save_role_bindings(bindings),
            lambda: self._secondary.save_role_bindings(bindings),
        )


class _DualAbacStore(AbacStore):
    def __init__(self, primary: AbacStore, secondary: AbacStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_policies(self) -> list:
        return _read_with_fallback(
            primary_fn=self._primary.load_policies,
            secondary_fn=self._secondary.load_policies,
            fallback_on_empty=_fallback_on_empty(),
            label="abac.load_policies",
        )

    def save_policies(self, policies: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_policies(policies),
            lambda: self._secondary.save_policies(policies),
        )


class _DualPrivacyStore(PrivacyStore):
    def __init__(self, primary: PrivacyStore, secondary: PrivacyStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_policies(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_policies,
            secondary_fn=self._secondary.load_policies,
            fallback_on_empty=_fallback_on_empty(),
            label="privacy.load_policies",
        )

    def save_policies(self, policies: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_policies(policies),
            lambda: self._secondary.save_policies(policies),
        )

    def register_policy(self, **kwargs):
        policy = self._primary.register_policy(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_policies,
                self._secondary.save_policies,
                policy,
            )
        return policy

    def update_policy(self, *, policy):
        updated = self._primary.update_policy(policy=policy)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_policies,
                self._secondary.save_policies,
                updated,
            )
        return updated


class _DualFleetStore(FleetStore):
    def __init__(self, primary: FleetStore, secondary: FleetStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_devices(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_devices,
            secondary_fn=self._secondary.load_devices,
            fallback_on_empty=_fallback_on_empty(),
            label="fleet.load_devices",
        )

    def save_devices(self, devices: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_devices(devices),
            lambda: self._secondary.save_devices(devices),
        )

    def register_device(self, **kwargs):
        device = self._primary.register_device(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_devices,
                self._secondary.save_devices,
                device,
            )
        return device

    def update_device(self, device):
        updated = self._primary.update_device(device)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_devices,
                self._secondary.save_devices,
                updated,
            )
        return updated

    def update_device_status(self, **kwargs):
        updated = self._primary.update_device_status(**kwargs)
        if updated is None:
            return None
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_devices,
                self._secondary.save_devices,
                updated,
            )
        return updated


class _DualWorkflowStore(WorkflowStore):
    def __init__(self, primary: WorkflowStore, secondary: WorkflowStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_workflows(self) -> list[WorkflowSpec]:
        return _read_with_fallback(
            primary_fn=self._primary.load_workflows,
            secondary_fn=self._secondary.load_workflows,
            fallback_on_empty=_fallback_on_empty(),
            label="workflows.load_workflows",
        )

    def save_workflows(self, workflows: Iterable[WorkflowSpec]) -> str:
        return _write_dual(
            lambda: self._primary.save_workflows(workflows),
            lambda: self._secondary.save_workflows(workflows),
        )

    def register_workflow(self, **kwargs) -> WorkflowSpec:
        workflow = self._primary.register_workflow(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_workflows,
                self._secondary.save_workflows,
                workflow,
            )
        return workflow

    def update_workflow(self, *, workflow: WorkflowSpec) -> WorkflowSpec:
        updated = self._primary.update_workflow(workflow=workflow)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_workflows,
                self._secondary.save_workflows,
                updated,
            )
        return updated

    def load_workflow_runs(self) -> list[WorkflowRun]:
        return _read_with_fallback(
            primary_fn=self._primary.load_workflow_runs,
            secondary_fn=self._secondary.load_workflow_runs,
            fallback_on_empty=_fallback_on_empty(),
            label="workflows.load_workflow_runs",
        )

    def save_workflow_runs(self, runs: Iterable[WorkflowRun]) -> str:
        return _write_dual(
            lambda: self._primary.save_workflow_runs(runs),
            lambda: self._secondary.save_workflow_runs(runs),
        )

    def register_workflow_run(self, **kwargs) -> WorkflowRun:
        run = self._primary.register_workflow_run(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_workflow_runs,
                self._secondary.save_workflow_runs,
                run,
            )
        return run

    def update_workflow_run(self, *, run: WorkflowRun) -> WorkflowRun:
        updated = self._primary.update_workflow_run(run=run)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_workflow_runs,
                self._secondary.save_workflow_runs,
                updated,
            )
        return updated

    def list_workflow_runs(self, **kwargs) -> list[WorkflowRun]:
        def _primary():
            return self._primary.list_workflow_runs(**kwargs)

        def _secondary():
            return self._secondary.list_workflow_runs(**kwargs)

        return _read_with_fallback(
            primary_fn=_primary,
            secondary_fn=_secondary,
            fallback_on_empty=_fallback_on_empty(),
            label="workflows.list_workflow_runs",
        )


class _DualDataFactoryStore(DataFactoryStore):
    def __init__(self, primary: DataFactoryStore, secondary: DataFactoryStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_models(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_models,
            secondary_fn=self._secondary.load_models,
            fallback_on_empty=_fallback_on_empty(),
            label="data_factory.load_models",
        )

    def save_models(self, models: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_models(models),
            lambda: self._secondary.save_models(models),
        )

    def register_model(self, **kwargs):
        model = self._primary.register_model(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_models,
                self._secondary.save_models,
                model,
            )
        return model

    def update_model(self, model):
        updated = self._primary.update_model(model)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_models,
                self._secondary.save_models,
                updated,
            )
        return updated

    def load_training_jobs(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_training_jobs,
            secondary_fn=self._secondary.load_training_jobs,
            fallback_on_empty=_fallback_on_empty(),
            label="data_factory.load_training_jobs",
        )

    def save_training_jobs(self, jobs: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_training_jobs(jobs),
            lambda: self._secondary.save_training_jobs(jobs),
        )

    def register_training_job(self, **kwargs):
        job = self._primary.register_training_job(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                job,
            )
        return job

    def update_training_job(self, *, job):
        updated = self._primary.update_training_job(job=job)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                updated,
            )
        return updated

    def get_training_job(self, job_id: str):
        def _primary():
            return self._primary.get_training_job(job_id)

        def _secondary():
            return self._secondary.get_training_job(job_id)

        return _read_with_fallback(
            primary_fn=_primary,
            secondary_fn=_secondary,
            fallback_on_empty=_fallback_on_empty(),
            label="data_factory.get_training_job",
        )

    def list_training_jobs(self, **kwargs):
        def _primary():
            return self._primary.list_training_jobs(**kwargs)

        def _secondary():
            return self._secondary.list_training_jobs(**kwargs)

        return _read_with_fallback(
            primary_fn=_primary,
            secondary_fn=_secondary,
            fallback_on_empty=_fallback_on_empty(),
            label="data_factory.list_training_jobs",
        )

    def mark_training_job_running(self, *, job_id: str):
        updated = self._primary.mark_training_job_running(job_id=job_id)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                updated,
            )
        return updated

    def mark_training_job_completed(self, **kwargs):
        updated = self._primary.mark_training_job_completed(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                updated,
            )
        return updated

    def mark_training_job_failed(self, **kwargs):
        updated = self._primary.mark_training_job_failed(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                updated,
            )
        return updated

    def mark_training_job_canceled(self, *, job_id: str):
        updated = self._primary.mark_training_job_canceled(job_id=job_id)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_training_jobs,
                self._secondary.save_training_jobs,
                updated,
            )
        return updated


class _DualConnectorStore(ConnectorStore):
    def __init__(self, primary: ConnectorStore, secondary: ConnectorStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_ocr_connectors(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_ocr_connectors,
            secondary_fn=self._secondary.load_ocr_connectors,
            fallback_on_empty=_fallback_on_empty(),
            label="connectors.load_ocr_connectors",
        )

    def save_ocr_connectors(self, connectors: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_ocr_connectors(connectors),
            lambda: self._secondary.save_ocr_connectors(connectors),
        )

    def register_ocr_connector(self, **kwargs):
        connector = self._primary.register_ocr_connector(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_ocr_connectors,
                self._secondary.save_ocr_connectors,
                connector,
            )
        return connector

    def update_ocr_connector(self, *, connector):
        updated = self._primary.update_ocr_connector(connector=connector)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_ocr_connectors,
                self._secondary.save_ocr_connectors,
                updated,
            )
        return updated


class _DualApiKeyStore(ApiKeyStore):
    def __init__(self, primary: ApiKeyStore, secondary: ApiKeyStore) -> None:
        self._primary = primary
        self._secondary = secondary

    def load_api_keys(self):
        return _read_with_fallback(
            primary_fn=self._primary.load_api_keys,
            secondary_fn=self._secondary.load_api_keys,
            fallback_on_empty=_fallback_on_empty(),
            label="api_keys.load_api_keys",
        )

    def save_api_keys(self, api_keys: Iterable) -> str:
        return _write_dual(
            lambda: self._primary.save_api_keys(api_keys),
            lambda: self._secondary.save_api_keys(api_keys),
        )

    def register_api_key(self, **kwargs):
        record = self._primary.register_api_key(**kwargs)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_api_keys,
                self._secondary.save_api_keys,
                record,
            )
        return record

    def update_api_key(self, api_key):
        updated = self._primary.update_api_key(api_key)
        if _write_mode() == "dual":
            _upsert_by_id(
                self._secondary.load_api_keys,
                self._secondary.save_api_keys,
                updated,
            )
        return updated


def get_control_plane_stores(base_uri: str) -> StoreBundle:
    global _STORE_BUNDLE, _STORE_KEY
    backend = os.getenv("CONTROL_PLANE_STORE", "json").strip().lower()
    env_name = os.getenv("ENV", "dev").strip().lower()
    if backend == "json" and env_name not in ("dev", "local", "test"):
        logger.warning(
            (
                "JSON control-plane store is intended for local/dev only; "
                "set CONTROL_PLANE_STORE=firestore."
            ),
            extra={"control_plane_store": backend, "env": env_name},
        )
    prefix = os.getenv("CONTROL_PLANE_COLLECTION_PREFIX", "").strip()
    read_mode = _read_mode()
    write_mode = _write_mode()
    fallback_on_empty = _fallback_on_empty()
    fallback_backend = _fallback_backend(backend)
    key = (
        base_uri,
        backend,
        prefix,
        read_mode,
        write_mode,
        fallback_backend,
        fallback_on_empty,
    )
    if _STORE_BUNDLE is not None and _STORE_KEY == key:
        return _STORE_BUNDLE
    primary = (
        gcp_get_store_bundle(base_uri)
        if backend == "firestore"
        else core_get_store_bundle(base_uri)
    )
    if (
        (read_mode == "fallback" or write_mode == "dual" or fallback_on_empty)
        and fallback_backend != backend
    ):
        secondary = (
            gcp_get_store_bundle(base_uri)
            if fallback_backend == "firestore"
            else core_get_store_bundle(base_uri)
        )
        bundle = StoreBundle(
            rbac=_DualRbacStore(primary.rbac, secondary.rbac),
            abac=_DualAbacStore(primary.abac, secondary.abac),
            privacy=_DualPrivacyStore(primary.privacy, secondary.privacy),
            fleet=_DualFleetStore(primary.fleet, secondary.fleet),
            workflows=_DualWorkflowStore(primary.workflows, secondary.workflows),
            data_factory=_DualDataFactoryStore(
                primary.data_factory, secondary.data_factory
            ),
            connectors=_DualConnectorStore(primary.connectors, secondary.connectors),
            api_keys=_DualApiKeyStore(primary.api_keys, secondary.api_keys),
        )
    else:
        bundle = primary
    _STORE_BUNDLE = bundle
    _STORE_KEY = key
    return _STORE_BUNDLE


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
        bindings = get_control_plane_stores(base_uri).rbac.load_role_bindings()
        roles = bindings.get(auth_context.api_key_id)
        if not roles:
            default_role = _default_role()
            roles = [default_role] if default_role else []
    permissions = _permissions_for_roles(roles)
    if "*" in permissions:
        return True
    return action in permissions


def abac_allowed(
    auth_context: AuthContext | None,
    action: str,
    base_uri: str,
) -> bool:
    policies = get_control_plane_stores(base_uri).abac.load_policies()
    default_allow = os.getenv("ABAC_DEFAULT_ALLOW", "1") == "1"
    attrs = abac_rules.build_attributes(auth_context, action)
    return abac_rules.evaluate_policies(policies, attrs, default_allow=default_allow)


def _default_role() -> str | None:
    value = os.getenv("RBAC_DEFAULT_ROLE", "reader").strip()
    return value or None


def _permissions_for_roles(roles: Iterable[str]) -> set[str]:
    permissions: set[str] = set()
    for role_name in roles:
        role = rbac_rules.DEFAULT_ROLES.get(role_name)
        if role:
            permissions.update(role.permissions)
    return permissions
