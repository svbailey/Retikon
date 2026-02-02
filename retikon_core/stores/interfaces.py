from __future__ import annotations

from typing import Iterable, Protocol

from retikon_core.api_keys.types import ApiKeyRecord
from retikon_core.auth.abac import Policy
from retikon_core.connectors.ocr import OcrConnector
from retikon_core.data_factory.model_registry import ModelRecord
from retikon_core.data_factory.training import TrainingJob
from retikon_core.fleet.types import DeviceRecord
from retikon_core.privacy.types import PrivacyPolicy
from retikon_core.workflows.types import WorkflowRun, WorkflowSpec, WorkflowStep


class RbacStore(Protocol):
    def load_role_bindings(self) -> dict[str, list[str]]:
        ...

    def save_role_bindings(self, bindings: dict[str, list[str]]) -> str:
        ...


class AbacStore(Protocol):
    def load_policies(self) -> list[Policy]:
        ...

    def save_policies(self, policies: Iterable[Policy]) -> str:
        ...


class PrivacyStore(Protocol):
    def load_policies(self) -> list[PrivacyPolicy]:
        ...

    def save_policies(self, policies: Iterable[PrivacyPolicy]) -> str:
        ...

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
        status: str = "active",
    ) -> PrivacyPolicy:
        ...

    def update_policy(self, *, policy: PrivacyPolicy) -> PrivacyPolicy:
        ...


class FleetStore(Protocol):
    def load_devices(self) -> list[DeviceRecord]:
        ...

    def save_devices(self, devices: Iterable[DeviceRecord]) -> str:
        ...

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
        ...

    def update_device(self, device: DeviceRecord) -> DeviceRecord:
        ...

    def update_device_status(
        self,
        *,
        device_id: str,
        status: str,
        last_seen_at: str | None = None,
    ) -> DeviceRecord | None:
        ...


class WorkflowStore(Protocol):
    def load_workflows(self) -> list[WorkflowSpec]:
        ...

    def save_workflows(self, workflows: Iterable[WorkflowSpec]) -> str:
        ...

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
        status: str = "active",
    ) -> WorkflowSpec:
        ...

    def update_workflow(self, *, workflow: WorkflowSpec) -> WorkflowSpec:
        ...

    def load_workflow_runs(self) -> list[WorkflowRun]:
        ...

    def save_workflow_runs(self, runs: Iterable[WorkflowRun]) -> str:
        ...

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
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
    ) -> WorkflowRun:
        ...

    def update_workflow_run(self, *, run: WorkflowRun) -> WorkflowRun:
        ...

    def list_workflow_runs(
        self,
        *,
        workflow_id: str | None = None,
        limit: int | None = None,
    ) -> list[WorkflowRun]:
        ...


class DataFactoryStore(Protocol):
    def load_models(self) -> list[ModelRecord]:
        ...

    def save_models(self, models: Iterable[ModelRecord]) -> str:
        ...

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
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        status: str = "active",
    ) -> ModelRecord:
        ...

    def update_model(self, model: ModelRecord) -> ModelRecord:
        ...

    def load_training_jobs(self) -> list[TrainingJob]:
        ...

    def save_training_jobs(self, jobs: Iterable[TrainingJob]) -> str:
        ...

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
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
    ) -> TrainingJob:
        ...

    def update_training_job(self, *, job: TrainingJob) -> TrainingJob:
        ...

    def get_training_job(self, job_id: str) -> TrainingJob | None:
        ...

    def list_training_jobs(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TrainingJob]:
        ...

    def mark_training_job_running(self, *, job_id: str) -> TrainingJob:
        ...

    def mark_training_job_completed(
        self,
        *,
        job_id: str,
        output: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> TrainingJob:
        ...

    def mark_training_job_failed(
        self,
        *,
        job_id: str,
        error: str | None = None,
    ) -> TrainingJob:
        ...

    def mark_training_job_canceled(self, *, job_id: str) -> TrainingJob:
        ...


class ConnectorStore(Protocol):
    def load_ocr_connectors(self) -> list[OcrConnector]:
        ...

    def save_ocr_connectors(self, connectors: Iterable[OcrConnector]) -> str:
        ...

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
        org_id: str | None = None,
        site_id: str | None = None,
        stream_id: str | None = None,
        status: str = "active",
    ) -> OcrConnector:
        ...

    def update_ocr_connector(self, *, connector: OcrConnector) -> OcrConnector:
        ...


class ApiKeyStore(Protocol):
    def load_api_keys(self) -> list[ApiKeyRecord]:
        ...

    def save_api_keys(self, api_keys: Iterable[ApiKeyRecord]) -> str:
        ...

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
        ...

    def update_api_key(self, api_key: ApiKeyRecord) -> ApiKeyRecord:
        ...
