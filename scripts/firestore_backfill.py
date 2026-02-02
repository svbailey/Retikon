from __future__ import annotations

import argparse
import os
from typing import Iterable

from retikon_core.config import get_config
from retikon_core.stores.registry import get_store_bundle as json_bundle
from retikon_gcp.stores import get_store_bundle as firestore_bundle


def _resolve_base_uri(cli_value: str | None) -> str:
    if cli_value:
        return cli_value
    config = get_config()
    return config.graph_root_uri()


def _maybe_print(msg: str) -> None:
    print(msg)


def _sync(
    name: str,
    items: Iterable[object],
    save_fn,
    dry_run: bool,
) -> None:
    materialized = list(items)
    count = len(materialized)
    if dry_run:
        _maybe_print(f"[dry-run] {name}: {count} items")
        return
    save_fn(materialized)
    _maybe_print(f"{name}: wrote {count} items")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backfill control-plane JSON data into Firestore."
    )
    parser.add_argument(
        "--base-uri",
        help="Graph root URI (defaults to env-derived GRAPH_BUCKET/GRAPH_PREFIX)",
    )
    parser.add_argument(
        "--project-id",
        help="GCP project for Firestore client (defaults to GOOGLE_CLOUD_PROJECT)",
    )
    parser.add_argument(
        "--collection-prefix",
        help=(
            "Firestore collection prefix "
            "(defaults to CONTROL_PLANE_COLLECTION_PREFIX)"
        ),
    )
    parser.add_argument(
        "--domain",
        action="append",
        choices=[
            "rbac",
            "abac",
            "privacy",
            "fleet",
            "workflows",
            "workflow_runs",
            "data_factory_models",
            "data_factory_jobs",
            "connectors",
            "api_keys",
            "all",
        ],
        default=["all"],
        help="Limit backfill to specific domain(s). Can be passed multiple times.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_uri = _resolve_base_uri(args.base_uri)
    project_id = args.project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
    prefix = args.collection_prefix or os.getenv("CONTROL_PLANE_COLLECTION_PREFIX", "")

    json_stores = json_bundle(base_uri)
    firestore_stores = firestore_bundle(
        base_uri,
        project_id=project_id,
        collection_prefix=prefix,
    )

    domains = set(args.domain)
    if "all" in domains:
        domains = {
            "rbac",
            "abac",
            "privacy",
            "fleet",
            "workflows",
            "workflow_runs",
            "data_factory_models",
            "data_factory_jobs",
            "connectors",
            "api_keys",
        }

    if "rbac" in domains:
        bindings = json_stores.rbac.load_role_bindings()
        if args.dry_run:
            _maybe_print(f"[dry-run] rbac: {len(bindings)} principals")
        else:
            firestore_stores.rbac.save_role_bindings(bindings)
            _maybe_print(f"rbac: wrote {len(bindings)} principals")

    if "abac" in domains:
        policies = json_stores.abac.load_policies()
        _sync(
            "abac",
            policies,
            firestore_stores.abac.save_policies,
            args.dry_run,
        )

    if "privacy" in domains:
        policies = json_stores.privacy.load_policies()
        _sync(
            "privacy",
            policies,
            firestore_stores.privacy.save_policies,
            args.dry_run,
        )

    if "fleet" in domains:
        devices = json_stores.fleet.load_devices()
        _sync(
            "fleet",
            devices,
            firestore_stores.fleet.save_devices,
            args.dry_run,
        )

    if "workflows" in domains:
        workflows = json_stores.workflows.load_workflows()
        _sync(
            "workflows",
            workflows,
            firestore_stores.workflows.save_workflows,
            args.dry_run,
        )

    if "workflow_runs" in domains:
        runs = json_stores.workflows.load_workflow_runs()
        _sync(
            "workflow_runs",
            runs,
            firestore_stores.workflows.save_workflow_runs,
            args.dry_run,
        )

    if "data_factory_models" in domains:
        models = json_stores.data_factory.load_models()
        _sync(
            "data_factory_models",
            models,
            firestore_stores.data_factory.save_models,
            args.dry_run,
        )

    if "data_factory_jobs" in domains:
        jobs = json_stores.data_factory.load_training_jobs()
        _sync(
            "data_factory_training_jobs",
            jobs,
            firestore_stores.data_factory.save_training_jobs,
            args.dry_run,
        )

    if "connectors" in domains:
        connectors = json_stores.connectors.load_ocr_connectors()
        _sync(
            "ocr_connectors",
            connectors,
            firestore_stores.connectors.save_ocr_connectors,
            args.dry_run,
        )

    if "api_keys" in domains:
        api_keys = json_stores.api_keys.load_api_keys()
        _sync(
            "api_keys",
            api_keys,
            firestore_stores.api_keys.save_api_keys,
            args.dry_run,
        )


if __name__ == "__main__":
    main()
