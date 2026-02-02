from __future__ import annotations

import os
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, cast

from google.cloud import firestore

from retikon_core.api_keys import store as api_key_store
from retikon_core.api_keys.types import ApiKeyRecord
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


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_list(items: Iterable[object] | None) -> tuple[str, ...] | None:
    if not items:
        return None
    cleaned = [str(item).strip().lower() for item in items if str(item).strip()]
    if not cleaned:
        return None
    deduped: list[str] = []
    for item in cleaned:
        if item not in deduped:
            deduped.append(item)
    return tuple(deduped)


class FirestoreStoreBase:
    def __init__(
        self,
        client: firestore.Client | None = None,
        *,
        project_id: str | None = None,
        collection_prefix: str | None = None,
    ) -> None:
        self._client = client or firestore.Client(project=project_id)
        if collection_prefix is None:
            collection_prefix = os.getenv("CONTROL_PLANE_COLLECTION_PREFIX", "")
        self._collection_prefix = collection_prefix.strip()

    def _collection(self, name: str) -> firestore.CollectionReference:
        prefix = self._collection_prefix
        if prefix:
            return self._client.collection(f"{prefix}{name}")
        return self._client.collection(name)

    def _doc_payload(self, doc: firestore.DocumentSnapshot) -> dict[str, object]:
        data = doc.to_dict() or {}
        if "id" not in data:
            data["id"] = doc.id
        return data

    def _commit_batches(
        self,
        *,
        sets: Iterable[tuple[firestore.DocumentReference, dict[str, object]]],
        deletes: Iterable[firestore.DocumentReference],
    ) -> None:
        batch = self._client.batch()
        count = 0
        for ref, payload in sets:
            batch.set(ref, payload)
            count += 1
            if count >= 450:
                batch.commit()
                batch = self._client.batch()
                count = 0
        for ref in deletes:
            batch.delete(ref)
            count += 1
            if count >= 450:
                batch.commit()
                batch = self._client.batch()
                count = 0
        if count:
            batch.commit()


class FirestoreRbacStore(FirestoreStoreBase, RbacStore):
    _collection_name = "rbac_bindings"

    def load_role_bindings(self) -> dict[str, list[str]]:
        bindings: dict[str, list[str]] = {}
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            principal_id = str(data.get("principal_id") or data.get("api_key_id") or "")
            roles = data.get("roles") or []
            if not principal_id or not isinstance(roles, list):
                continue
            bindings[principal_id] = [str(role) for role in roles if role]
        return bindings

    def save_role_bindings(self, bindings: dict[str, list[str]]) -> str:
        collection = self._collection(self._collection_name)
        existing_ids = {doc.id for doc in collection.stream()}
        records: list[tuple[firestore.DocumentReference, dict[str, object]]] = []
        for principal_id, roles in bindings.items():
            doc_id = principal_id or str(uuid.uuid4())
            payload: dict[str, object] = {
                "id": doc_id,
                "org_id": None,
                "site_id": None,
                "stream_id": None,
                "status": "active",
                "created_at": _now_iso(),
                "updated_at": _now_iso(),
                "principal_type": "api_key",
                "principal_id": principal_id,
                "roles": list(roles),
            }
            records.append((collection.document(doc_id), payload))
        record_ids = {ref.id for ref, _ in records}
        delete_refs = [
            collection.document(doc_id)
            for doc_id in existing_ids
            if doc_id not in record_ids
        ]
        self._commit_batches(sets=records, deletes=delete_refs)
        return self._collection_name


class FirestoreAbacStore(FirestoreStoreBase, AbacStore):
    _collection_name = "abac_policies"

    def load_policies(self) -> list[Policy]:
        policies: list[Policy] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            policy_id = str(data.get("id") or doc.id)
            policies.append(
                Policy(
                    id=policy_id,
                    effect=str(data.get("effect", "allow")),
                    conditions=_coerce_dict(data.get("conditions")),
                    org_id=_coerce_optional_str(data.get("org_id")),
                    site_id=_coerce_optional_str(data.get("site_id")),
                    stream_id=_coerce_optional_str(data.get("stream_id")),
                    status=str(data.get("status", "active")),
                    created_at=str(data.get("created_at", "")),
                    updated_at=str(data.get("updated_at", "")),
                    description=_coerce_optional_str(data.get("description")),
                )
            )
        return policies

    def save_policies(self, policies: Iterable[Policy]) -> str:
        collection = self._collection(self._collection_name)
        existing_ids = {doc.id for doc in collection.stream()}
        records: list[tuple[firestore.DocumentReference, dict[str, object]]] = []
        for policy in policies:
            doc_id = policy.id or str(uuid.uuid4())
            created_at = policy.created_at or _now_iso()
            updated_at = policy.updated_at or _now_iso()
            payload: dict[str, object] = {
                "id": doc_id,
                "org_id": policy.org_id,
                "site_id": policy.site_id,
                "stream_id": policy.stream_id,
                "status": policy.status,
                "created_at": created_at,
                "updated_at": updated_at,
                "effect": policy.effect,
                "conditions": dict(policy.conditions),
                "description": policy.description,
            }
            records.append((collection.document(doc_id), payload))
        record_ids = {ref.id for ref, _ in records}
        delete_refs = [
            collection.document(doc_id)
            for doc_id in existing_ids
            if doc_id not in record_ids
        ]
        self._commit_batches(sets=records, deletes=delete_refs)
        return self._collection_name


class FirestorePrivacyStore(FirestoreStoreBase, PrivacyStore):
    _collection_name = "privacy_policies"

    def load_policies(self) -> list[PrivacyPolicy]:
        policies: list[PrivacyPolicy] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            policies.append(privacy_store._policy_from_dict(data))
        return policies

    def save_policies(self, policies: Iterable[PrivacyPolicy]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._collection_name,
            items=policies,
        )

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
        now = _now_iso()
        policy = PrivacyPolicy(
            id=str(uuid.uuid4()),
            name=name,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            modalities=_normalize_list(modalities),
            contexts=_normalize_list(contexts),
            redaction_types=_normalize_list(redaction_types) or ("pii",),
            enabled=enabled,
            created_at=now,
            updated_at=now,
            status=status,
        )
        self._collection(self._collection_name).document(policy.id).set(
            asdict(policy)
        )
        return policy

    def update_policy(self, *, policy: PrivacyPolicy) -> PrivacyPolicy:
        self._collection(self._collection_name).document(policy.id).set(
            asdict(policy)
        )
        return policy


class FirestoreFleetStore(FirestoreStoreBase, FleetStore):
    _collection_name = "fleet_devices"

    def load_devices(self) -> list[DeviceRecord]:
        devices: list[DeviceRecord] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            devices.append(fleet_store._device_from_dict(data))
        return devices

    def save_devices(self, devices: Iterable[DeviceRecord]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._collection_name,
            items=devices,
        )

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
        now = _now_iso()
        device = DeviceRecord(
            id=str(uuid.uuid4()),
            name=name,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            tags=_normalize_list(tags),
            status=status,
            firmware_version=firmware_version,
            last_seen_at=last_seen_at,
            metadata=metadata,
            created_at=now,
            updated_at=now,
        )
        self._collection(self._collection_name).document(device.id).set(
            asdict(device)
        )
        return device

    def update_device(self, device: DeviceRecord) -> DeviceRecord:
        self._collection(self._collection_name).document(device.id).set(
            asdict(device)
        )
        return device

    def update_device_status(
        self,
        *,
        device_id: str,
        status: str,
        last_seen_at: str | None = None,
    ) -> DeviceRecord | None:
        doc_ref = self._collection(self._collection_name).document(device_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _update(
            transaction: firestore.Transaction,
        ) -> DeviceRecord | None:
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                return None
            data = self._doc_payload(snapshot)
            existing = fleet_store._device_from_dict(data)
            now = _now_iso()
            updated = DeviceRecord(
                id=existing.id,
                name=existing.name,
                org_id=existing.org_id,
                site_id=existing.site_id,
                stream_id=existing.stream_id,
                tags=existing.tags,
                status=status,
                firmware_version=existing.firmware_version,
                last_seen_at=last_seen_at or now,
                metadata=existing.metadata,
                created_at=existing.created_at,
                updated_at=now,
            )
            transaction.set(doc_ref, asdict(updated))
            return updated

        return _update(transaction)


class FirestoreWorkflowStore(FirestoreStoreBase, WorkflowStore):
    _collection_name = "workflow_specs"
    _run_collection_name = "workflow_runs"

    def load_workflows(self) -> list[WorkflowSpec]:
        workflows: list[WorkflowSpec] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            workflows.append(workflow_store._workflow_from_dict(data))
        return workflows

    def save_workflows(self, workflows: Iterable[WorkflowSpec]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._collection_name,
            items=workflows,
        )

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
        now = _now_iso()
        workflow = WorkflowSpec(
            id=str(uuid.uuid4()),
            name=name,
            description=description,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            schedule=schedule,
            enabled=enabled,
            steps=tuple(steps) if steps else (),
            created_at=now,
            updated_at=now,
            status=status,
        )
        self._collection(self._collection_name).document(workflow.id).set(
            asdict(workflow)
        )
        return workflow

    def update_workflow(self, *, workflow: WorkflowSpec) -> WorkflowSpec:
        self._collection(self._collection_name).document(workflow.id).set(
            asdict(workflow)
        )
        return workflow

    def load_workflow_runs(self) -> list[WorkflowRun]:
        runs: list[WorkflowRun] = []
        for doc in self._collection(self._run_collection_name).stream():
            data = self._doc_payload(doc)
            runs.append(workflow_store._run_from_dict(data))
        return runs

    def save_workflow_runs(self, runs: Iterable[WorkflowRun]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._run_collection_name,
            items=runs,
        )

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
        now = _now_iso()
        if org_id is None and site_id is None and stream_id is None:
            doc = self._collection(self._collection_name).document(workflow_id).get()
            if doc.exists:
                workflow = workflow_store._workflow_from_dict(self._doc_payload(doc))
                org_id = workflow.org_id
                site_id = workflow.site_id
                stream_id = workflow.stream_id
        run = WorkflowRun(
            id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            status=status,
            started_at=started_at or now,
            finished_at=finished_at,
            error=error,
            output=output,
            triggered_by=triggered_by,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            created_at=now,
            updated_at=now,
        )
        self._collection(self._run_collection_name).document(run.id).set(asdict(run))
        return run

    def update_workflow_run(self, *, run: WorkflowRun) -> WorkflowRun:
        doc_ref = self._collection(self._run_collection_name).document(run.id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _update(transaction: firestore.Transaction) -> WorkflowRun:
            snapshot = doc_ref.get(transaction=transaction)
            if snapshot.exists:
                existing = workflow_store._run_from_dict(self._doc_payload(snapshot))
                created_at = run.created_at or existing.created_at
                org_id = run.org_id if run.org_id is not None else existing.org_id
                site_id = run.site_id if run.site_id is not None else existing.site_id
                stream_id = (
                    run.stream_id if run.stream_id is not None else existing.stream_id
                )
            else:
                created_at = run.created_at or _now_iso()
                org_id = run.org_id
                site_id = run.site_id
                stream_id = run.stream_id
            updated = WorkflowRun(
                id=run.id,
                workflow_id=run.workflow_id,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                error=run.error,
                output=run.output,
                triggered_by=run.triggered_by,
                org_id=org_id,
                site_id=site_id,
                stream_id=stream_id,
                created_at=created_at,
                updated_at=run.updated_at or _now_iso(),
            )
            transaction.set(doc_ref, asdict(updated))
            return updated

        return _update(transaction)

    def list_workflow_runs(
        self,
        *,
        workflow_id: str | None = None,
        limit: int | None = None,
    ) -> list[WorkflowRun]:
        query = self._collection(self._run_collection_name)
        org_id: str | None = None
        if workflow_id:
            doc = self._collection(self._collection_name).document(workflow_id).get()
            if doc.exists:
                workflow = workflow_store._workflow_from_dict(self._doc_payload(doc))
                org_id = workflow.org_id
        if org_id:
            query = query.where("org_id", "==", org_id)
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        if limit is not None:
            query = query.limit(limit)
        runs = [
            workflow_store._run_from_dict(self._doc_payload(doc))
            for doc in query.stream()
        ]
        if workflow_id:
            runs = [run for run in runs if run.workflow_id == workflow_id]
        if limit is not None:
            runs = runs[:limit]
        return runs


class FirestoreDataFactoryStore(FirestoreStoreBase, DataFactoryStore):
    _model_collection_name = "data_factory_models"
    _job_collection_name = "data_factory_training_jobs"

    def load_models(self) -> list[ModelRecord]:
        models: list[ModelRecord] = []
        for doc in self._collection(self._model_collection_name).stream():
            data = self._doc_payload(doc)
            models.append(model_registry._model_from_dict(data))
        return models

    def save_models(self, models: Iterable[ModelRecord]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._model_collection_name,
            items=models,
        )

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
        now = _now_iso()
        model = ModelRecord(
            id=str(uuid.uuid4()),
            name=name,
            version=version,
            description=description,
            task=task,
            framework=framework,
            tags=_normalize_list(tags),
            metrics=metrics,
            created_at=now,
            updated_at=now,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            status=status,
        )
        self._collection(self._model_collection_name).document(model.id).set(
            asdict(model)
        )
        return model

    def update_model(self, model: ModelRecord) -> ModelRecord:
        self._collection(self._model_collection_name).document(model.id).set(
            asdict(model)
        )
        return model

    def load_training_jobs(self) -> list[TrainingJob]:
        jobs: list[TrainingJob] = []
        for doc in self._collection(self._job_collection_name).stream():
            data = self._doc_payload(doc)
            jobs.append(training._job_from_dict(data))
        return jobs

    def save_training_jobs(self, jobs: Iterable[TrainingJob]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._job_collection_name,
            items=jobs,
        )

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
        job = training.create_training_job(
            dataset_id=dataset_id or "",
            model_id=model_id,
            epochs=epochs or 10,
            batch_size=batch_size or 16,
            learning_rate=learning_rate or 1e-4,
            labels=labels,
            status=status,
            output=output,
            metrics=metrics,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
        )
        self._collection(self._job_collection_name).document(job.id).set(asdict(job))
        return job

    def update_training_job(self, *, job: TrainingJob) -> TrainingJob:
        self._collection(self._job_collection_name).document(job.id).set(asdict(job))
        return job

    def get_training_job(self, job_id: str) -> TrainingJob | None:
        doc = self._collection(self._job_collection_name).document(job_id).get()
        if not doc.exists:
            return None
        return training._job_from_dict(self._doc_payload(doc))

    def list_training_jobs(
        self,
        *,
        status: str | None = None,
        limit: int | None = None,
    ) -> list[TrainingJob]:
        query = self._collection(self._job_collection_name)
        if status:
            query = query.where("status", "==", status)
        query = query.order_by("created_at", direction=firestore.Query.DESCENDING)
        if limit is not None:
            query = query.limit(limit)
        return [
            training._job_from_dict(self._doc_payload(doc)) for doc in query.stream()
        ]

    def _update_training_job(
        self,
        *,
        job_id: str,
        update_fn: Callable[[TrainingJob], TrainingJob],
    ) -> TrainingJob:
        doc_ref = self._collection(self._job_collection_name).document(job_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _update(transaction: firestore.Transaction) -> TrainingJob:
            snapshot = doc_ref.get(transaction=transaction)
            if not snapshot.exists:
                raise ValueError("Training job not found")
            job = training._job_from_dict(self._doc_payload(snapshot))
            updated = update_fn(job)
            transaction.set(doc_ref, asdict(updated))
            return updated

        return _update(transaction)

    def mark_training_job_running(self, *, job_id: str) -> TrainingJob:
        return self._update_training_job(
            job_id=job_id,
            update_fn=lambda job: training._update_training_job(
                job=job,
                status="running",
                started_at=_now_iso(),
            ),
        )

    def mark_training_job_completed(
        self,
        *,
        job_id: str,
        output: dict[str, object] | None = None,
        metrics: dict[str, object] | None = None,
    ) -> TrainingJob:
        return self._update_training_job(
            job_id=job_id,
            update_fn=lambda job: training._update_training_job(
                job=job,
                status="completed",
                finished_at=_now_iso(),
                output=output,
                metrics=metrics,
            ),
        )

    def mark_training_job_failed(
        self,
        *,
        job_id: str,
        error: str | None = None,
    ) -> TrainingJob:
        return self._update_training_job(
            job_id=job_id,
            update_fn=lambda job: training._update_training_job(
                job=job,
                status="failed",
                finished_at=_now_iso(),
                error=error,
            ),
        )

    def mark_training_job_canceled(self, *, job_id: str) -> TrainingJob:
        return self._update_training_job(
            job_id=job_id,
            update_fn=lambda job: training._update_training_job(
                job=job,
                status="canceled",
                finished_at=_now_iso(),
            ),
        )


class FirestoreConnectorStore(FirestoreStoreBase, ConnectorStore):
    _collection_name = "ocr_connectors"

    def load_ocr_connectors(self) -> list[OcrConnector]:
        connectors: list[OcrConnector] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            connectors.append(ocr_store._connector_from_dict(data))
        return connectors

    def save_ocr_connectors(self, connectors: Iterable[OcrConnector]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._collection_name,
            items=connectors,
        )

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
        now = _now_iso()
        connector = OcrConnector(
            id=str(uuid.uuid4()),
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
            created_at=now,
            updated_at=now,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            status=status,
        )
        ocr_store._validate_connector(connector)
        self._collection(self._collection_name).document(connector.id).set(
            asdict(connector)
        )
        return connector

    def update_ocr_connector(self, *, connector: OcrConnector) -> OcrConnector:
        ocr_store._validate_connector(connector)
        self._collection(self._collection_name).document(connector.id).set(
            asdict(connector)
        )
        return connector


class FirestoreApiKeyStore(FirestoreStoreBase, ApiKeyStore):
    _collection_name = "api_keys"

    def load_api_keys(self) -> list[ApiKeyRecord]:
        keys: list[ApiKeyRecord] = []
        for doc in self._collection(self._collection_name).stream():
            data = self._doc_payload(doc)
            keys.append(api_key_store._api_key_from_dict(data))
        return keys

    def save_api_keys(self, api_keys: Iterable[ApiKeyRecord]) -> str:
        return _save_dataclass_collection(
            self,
            collection_name=self._collection_name,
            items=api_keys,
        )

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
        now = _now_iso()
        api_key = ApiKeyRecord(
            id=str(uuid.uuid4()),
            name=name,
            key_hash=key_hash,
            org_id=org_id,
            site_id=site_id,
            stream_id=stream_id,
            status=status,
            scopes=_normalize_list(scopes),
            last_used_at=last_used_at,
            created_at=now,
            updated_at=now,
        )
        self._collection(self._collection_name).document(api_key.id).set(
            asdict(api_key)
        )
        return api_key

    def update_api_key(self, api_key: ApiKeyRecord) -> ApiKeyRecord:
        self._collection(self._collection_name).document(api_key.id).set(
            asdict(api_key)
        )
        return api_key


def _save_dataclass_collection(
    store: FirestoreStoreBase,
    *,
    collection_name: str,
    items: Iterable[object],
) -> str:
    collection = store._collection(collection_name)
    existing_ids = {doc.id for doc in collection.stream()}
    sets: list[tuple[firestore.DocumentReference, dict[str, object]]] = []
    item_ids: set[str] = set()
    for item in items:
        payload = cast(dict[str, object], asdict(cast(Any, item)))
        doc_id = str(payload.get("id") or uuid.uuid4())
        payload["id"] = doc_id
        sets.append((collection.document(doc_id), payload))
        item_ids.add(doc_id)
    deletes = [
        collection.document(doc_id)
        for doc_id in existing_ids
        if doc_id not in item_ids
    ]
    store._commit_batches(sets=sets, deletes=deletes)
    return collection_name


def _coerce_dict(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
