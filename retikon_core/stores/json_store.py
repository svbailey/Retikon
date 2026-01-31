from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Iterable

import fsspec

from retikon_core.api_keys import store as api_key_store
from retikon_core.api_keys.types import ApiKeyRecord
from retikon_core.auth import abac as abac_store
from retikon_core.auth import rbac as rbac_store
from retikon_core.auth.abac import Policy
from retikon_core.connectors import ocr as ocr_store
from retikon_core.connectors.ocr import OcrConnector
from retikon_core.data_factory import model_registry, training
from retikon_core.data_factory.model_registry import ModelRecord
from retikon_core.data_factory.training import TrainingJob
from retikon_core.fleet import store as fleet_store
from retikon_core.fleet.types import DeviceRecord
from retikon_core.privacy import store as privacy_store
from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.storage.paths import join_uri
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
from retikon_core.workflows import store as workflow_store
from retikon_core.workflows.types import WorkflowRun, WorkflowSpec, WorkflowStep


class JsonRbacStore(RbacStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_role_bindings(self) -> dict[str, list[str]]:
        return rbac_store.load_role_bindings(self._base_uri)

    def save_role_bindings(self, bindings: dict[str, list[str]]) -> str:
        uri = self._bindings_uri()
        fs, path = fsspec.core.url_to_fs(uri)
        fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "bindings": [
                {"api_key_id": key, "roles": list(roles)}
                for key, roles in bindings.items()
            ],
        }
        with fs.open(path, "wb") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        return uri

    def _bindings_uri(self) -> str:
        override = os.getenv("RBAC_BINDINGS_URI")
        if override:
            return override
        return join_uri(self._base_uri, "control", "rbac_bindings.json")


class JsonAbacStore(AbacStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_policies(self) -> list[Policy]:
        return abac_store.load_policies(self._base_uri)

    def save_policies(self, policies: Iterable[Policy]) -> str:
        uri = self._policies_uri()
        fs, path = fsspec.core.url_to_fs(uri)
        fs.makedirs("/".join(path.split("/")[:-1]), exist_ok=True)
        payload = {
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "policies": [
                {
                    "id": policy.id,
                    "effect": policy.effect,
                    "conditions": policy.conditions,
                }
                for policy in policies
            ],
        }
        with fs.open(path, "wb") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True).encode("utf-8"))
        return uri

    def _policies_uri(self) -> str:
        override = os.getenv("ABAC_POLICY_URI")
        if override:
            return override
        return join_uri(self._base_uri, "control", "abac_policies.json")


class JsonPrivacyStore(PrivacyStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_policies(self) -> list[PrivacyPolicy]:
        return privacy_store.load_privacy_policies(self._base_uri)

    def save_policies(self, policies: Iterable[PrivacyPolicy]) -> str:
        return privacy_store.save_privacy_policies(self._base_uri, policies)

    def register_policy(
        self,
        *,
        name: str,
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        modalities: Iterable[str] | None = None,
        contexts: Iterable[str] | None = None,
        redaction_types: Iterable[str] | None = None,
        enabled: bool = True,
    ) -> PrivacyPolicy:
        return privacy_store.register_privacy_policy(
            base_uri=self._base_uri,
            name=name,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            modalities=modalities,
            contexts=contexts,
            redaction_types=redaction_types,
            enabled=enabled,
        )

    def update_policy(self, *, policy: PrivacyPolicy) -> PrivacyPolicy:
        return privacy_store.update_privacy_policy(
            base_uri=self._base_uri,
            policy=policy,
        )


class JsonFleetStore(FleetStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_devices(self) -> list[DeviceRecord]:
        return fleet_store.load_devices(self._base_uri)

    def save_devices(self, devices: Iterable[DeviceRecord]) -> str:
        return fleet_store.save_devices(self._base_uri, devices)

    def register_device(
        self,
        *,
        name: str,
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        tags: Iterable[str] | None = None,
        status: str = "unknown",
        firmware_version: str | None = None,
        last_seen_at: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> DeviceRecord:
        return fleet_store.register_device(
            base_uri=self._base_uri,
            name=name,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            tags=tags,
            status=status,
            firmware_version=firmware_version,
            last_seen_at=last_seen_at,
            metadata=metadata,
        )

    def update_device(self, device: DeviceRecord) -> DeviceRecord:
        return fleet_store.update_device(self._base_uri, device)

    def update_device_status(
        self,
        *,
        device_id: str,
        status: str,
        last_seen_at: str | None = None,
    ) -> DeviceRecord | None:
        return fleet_store.update_device_status(
            base_uri=self._base_uri,
            device_id=device_id,
            status=status,
            last_seen_at=last_seen_at,
        )


class JsonWorkflowStore(WorkflowStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_workflows(self) -> list[WorkflowSpec]:
        return workflow_store.load_workflows(self._base_uri)

    def save_workflows(self, workflows: Iterable[WorkflowSpec]) -> str:
        return workflow_store.save_workflows(self._base_uri, workflows)

    def register_workflow(
        self,
        *,
        name: str,
        description: str | None = None,
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        schedule: str | None = None,
        enabled: bool = True,
        steps: Iterable[WorkflowStep] | None = None,
    ) -> WorkflowSpec:
        return workflow_store.register_workflow(
            base_uri=self._base_uri,
            name=name,
            description=description,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            schedule=schedule,
            enabled=enabled,
            steps=steps,
        )

    def update_workflow(self, *, workflow: WorkflowSpec) -> WorkflowSpec:
        return workflow_store.update_workflow(
            base_uri=self._base_uri,
            workflow=workflow,
        )

    def load_workflow_runs(self) -> list[WorkflowRun]:
        return workflow_store.load_workflow_runs(self._base_uri)

    def save_workflow_runs(self, runs: Iterable[WorkflowRun]) -> str:
        return workflow_store.save_workflow_runs(self._base_uri, runs)

    def register_workflow_run(
        self,
        *,
        workflow_id: str,
        status: str = "queued",
        started_at: str | None = None,
        finished_at: str | None = None,
        error: str | None = None,
        output: dict[str, object] | None = None,
        triggered_by: str | None = None,
    ) -> WorkflowRun:
        return workflow_store.register_workflow_run(
            base_uri=self._base_uri,
            workflow_id=workflow_id,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            error=error,
            output=output,
            triggered_by=triggered_by,
        )

    def update_workflow_run(self, *, run: WorkflowRun) -> WorkflowRun:
        return workflow_store.update_workflow_run(base_uri=self._base_uri, run=run)

    def list_workflow_runs(
        self,
        *,
        workflow_id: str | None = None,
        limit: int | None = None,
    ) -> list[WorkflowRun]:
        return workflow_store.list_workflow_runs(
            self._base_uri,
            workflow_id=workflow_id,
            limit=limit,
        )


class JsonDataFactoryStore(DataFactoryStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_models(self) -> list[ModelRecord]:
        return model_registry.load_models(self._base_uri)

    def save_models(self, models: Iterable[ModelRecord]) -> str:
        return model_registry.save_models(self._base_uri, models)

    def register_model(
        self,
        *,
        name: str,
        version: str,
        description: str | None = None,
        task: str | None = None,
        framework: str | None = None,
        tags: Iterable[str] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> ModelRecord:
        return model_registry.register_model(
            base_uri=self._base_uri,
            name=name,
            version=version,
            description=description,
            task=task,
            framework=framework,
            tags=tags,
            metrics=metrics,
        )

    def update_model(self, model: ModelRecord) -> ModelRecord:
        return model_registry.update_model(self._base_uri, model)

    def load_training_jobs(self) -> list[TrainingJob]:
        return training.load_training_jobs(self._base_uri)

    def save_training_jobs(self, jobs: Iterable[TrainingJob]) -> str:
        return training.save_training_jobs(self._base_uri, jobs)

    def register_training_job(
        self,
        *,
        model_id: str,
        dataset_id: str | None = None,
        epochs: int | None = None,
        batch_size: int | None = None,
        learning_rate: float | None = None,
        labels: Iterable[str] | None = None,
        status: str = "planned",
        output: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> TrainingJob:
        return training.register_training_job(
            base_uri=self._base_uri,
            model_id=model_id,
            dataset_id=dataset_id,
            epochs=epochs,
            batch_size=batch_size,
            learning_rate=learning_rate,
            labels=labels,
            status=status,
            output=output,
            metrics=metrics,
        )

    def update_training_job(self, *, job: TrainingJob) -> TrainingJob:
        return training.update_training_job(base_uri=self._base_uri, job=job)

    def get_training_job(self, job_id: str) -> TrainingJob | None:
        return training.get_training_job(self._base_uri, job_id)

    def list_training_jobs(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TrainingJob]:
        return training.list_training_jobs(
            self._base_uri,
            status=status,
            limit=limit,
        )

    def mark_training_job_running(self, *, job_id: str) -> TrainingJob:
        return training.mark_training_job_running(
            base_uri=self._base_uri,
            job_id=job_id,
        )

    def mark_training_job_completed(
        self,
        *,
        job_id: str,
        output: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> TrainingJob:
        return training.mark_training_job_completed(
            base_uri=self._base_uri,
            job_id=job_id,
            output=output,
            metrics=metrics,
        )

    def mark_training_job_failed(
        self,
        *,
        job_id: str,
        error: str | None = None,
    ) -> TrainingJob:
        return training.mark_training_job_failed(
            base_uri=self._base_uri,
            job_id=job_id,
            error=error,
        )

    def mark_training_job_canceled(self, *, job_id: str) -> TrainingJob:
        return training.mark_training_job_canceled(
            base_uri=self._base_uri,
            job_id=job_id,
        )


class JsonConnectorStore(ConnectorStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_ocr_connectors(self) -> list[OcrConnector]:
        return ocr_store.load_ocr_connectors(self._base_uri)

    def save_ocr_connectors(self, connectors: Iterable[OcrConnector]) -> str:
        return ocr_store.save_ocr_connectors(self._base_uri, connectors)

    def register_ocr_connector(
        self,
        *,
        name: str,
        url: str,
        auth_type: str = "none",
        auth_header: str | None = None,
        token_env: str | None = None,
        enabled: bool = True,
        is_default: bool = False,
        max_pages: int | None = None,
        timeout_s: float | None = None,
        notes: str | None = None,
    ) -> OcrConnector:
        return ocr_store.register_ocr_connector(
            base_uri=self._base_uri,
            name=name,
            url=url,
            auth_type=auth_type,
            auth_header=auth_header,
            token_env=token_env,
            enabled=enabled,
            is_default=is_default,
            max_pages=max_pages,
            timeout_s=timeout_s,
            notes=notes,
        )

    def update_ocr_connector(self, *, connector: OcrConnector) -> OcrConnector:
        return ocr_store.update_ocr_connector(
            base_uri=self._base_uri,
            connector=connector,
        )


class JsonApiKeyStore(ApiKeyStore):
    def __init__(self, base_uri: str) -> None:
        self._base_uri = base_uri

    def load_api_keys(self) -> list[ApiKeyRecord]:
        return api_key_store.load_api_keys(self._base_uri)

    def save_api_keys(self, api_keys: Iterable[ApiKeyRecord]) -> str:
        return api_key_store.save_api_keys(self._base_uri, api_keys)

    def register_api_key(
        self,
        *,
        name: str,
        key_hash: str,
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        status: str = "active",
        scopes: Iterable[str] | None = None,
        last_used_at: str | None = None,
    ) -> ApiKeyRecord:
        return api_key_store.register_api_key(
            base_uri=self._base_uri,
            name=name,
            key_hash=key_hash,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            status=status,
            scopes=scopes,
            last_used_at=last_used_at,
        )

    def update_api_key(self, api_key: ApiKeyRecord) -> ApiKeyRecord:
        return api_key_store.update_api_key(self._base_uri, api_key)
