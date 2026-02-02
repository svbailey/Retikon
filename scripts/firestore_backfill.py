from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import asdict, is_dataclass
from typing import Iterable, Mapping, Sequence

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


def _normalize(item: object) -> object:
    if is_dataclass(item):
        return asdict(item)
    if isinstance(item, Mapping):
        return dict(item)
    if hasattr(item, "__dict__"):
        return dict(item.__dict__)
    return item


def _item_key(item: object) -> str | None:
    if isinstance(item, Mapping):
        for key in ("id", "name", "key_hash", "principal_id", "api_key_id"):
            value = item.get(key)
            if value:
                return str(value)
        return None
    for key in ("id", "name", "key_hash", "principal_id", "api_key_id"):
        if hasattr(item, key):
            value = getattr(item, key)
            if value:
                return str(value)
    return None


def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sample_items(
    items: Sequence[object],
    sample_size: int,
) -> list[tuple[str | None, str]]:
    samples: list[tuple[str | None, str]] = []
    for item in items:
        payload = _normalize(item)
        samples.append((_item_key(item), _hash_payload(payload)))
    if not samples:
        return []
    if all(key is not None for key, _hash in samples):
        samples.sort(key=lambda entry: entry[0] or "")
    else:
        samples.sort(key=lambda entry: entry[1])
    return samples[:sample_size]


def _compare_samples(
    json_samples: list[tuple[str | None, str]],
    fs_samples: list[tuple[str | None, str]],
) -> dict[str, object]:
    if not json_samples and not fs_samples:
        return {"mode": "empty", "mismatch_count": 0, "mismatches": []}
    keyed = all(key is not None for key, _hash in json_samples + fs_samples)
    if keyed:
        json_map = {key: hash_value for key, hash_value in json_samples if key}
        fs_map = {key: hash_value for key, hash_value in fs_samples if key}
        mismatches = [
            key
            for key in sorted(set(json_map) | set(fs_map))
            if json_map.get(key) != fs_map.get(key)
        ]
        return {
            "mode": "keyed",
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "json_sample": json_map,
            "firestore_sample": fs_map,
        }
    json_hashes = [hash_value for _key, hash_value in json_samples]
    fs_hashes = [hash_value for _key, hash_value in fs_samples]
    mismatch_count = 0 if sorted(json_hashes) == sorted(fs_hashes) else 1
    return {
        "mode": "hashes",
        "mismatch_count": mismatch_count,
        "mismatches": [] if mismatch_count == 0 else ["hash_mismatch"],
        "json_sample": json_hashes,
        "firestore_sample": fs_hashes,
    }


def _parity_report_list(
    name: str,
    json_items: Sequence[object],
    firestore_items: Sequence[object],
    sample_size: int,
) -> dict[str, object]:
    json_samples = _sample_items(list(json_items), sample_size)
    fs_samples = _sample_items(list(firestore_items), sample_size)
    comparison = _compare_samples(json_samples, fs_samples)
    return {
        "domain": name,
        "json_count": len(json_items),
        "firestore_count": len(firestore_items),
        "sample_size": min(sample_size, len(json_items), len(firestore_items)),
        "comparison": comparison,
    }


def _parity_report_rbac(
    json_bindings: Mapping[str, Iterable[str]],
    firestore_bindings: Mapping[str, Iterable[str]],
    sample_size: int,
) -> dict[str, object]:
    json_map = {
        key: _hash_payload({"principal": key, "roles": sorted(list(roles))})
        for key, roles in json_bindings.items()
    }
    fs_map = {
        key: _hash_payload({"principal": key, "roles": sorted(list(roles))})
        for key, roles in firestore_bindings.items()
    }
    keys = sorted(set(json_map) | set(fs_map))
    sample_keys = keys[:sample_size]
    json_sample = {key: json_map.get(key, "") for key in sample_keys}
    fs_sample = {key: fs_map.get(key, "") for key in sample_keys}
    mismatches = [
        key for key in sample_keys if json_sample.get(key) != fs_sample.get(key)
    ]
    return {
        "domain": "rbac",
        "json_count": len(json_map),
        "firestore_count": len(fs_map),
        "sample_size": len(sample_keys),
        "comparison": {
            "mode": "keyed",
            "mismatch_count": len(mismatches),
            "mismatches": mismatches,
            "json_sample": json_sample,
            "firestore_sample": fs_sample,
        },
    }


def _run_parity_checks(
    *,
    json_stores,
    firestore_stores,
    domains: set[str],
    sample_size: int,
) -> list[dict[str, object]]:
    reports: list[dict[str, object]] = []
    if "rbac" in domains:
        reports.append(
            _parity_report_rbac(
                json_stores.rbac.load_role_bindings(),
                firestore_stores.rbac.load_role_bindings(),
                sample_size,
            )
        )
    if "abac" in domains:
        reports.append(
            _parity_report_list(
                "abac",
                json_stores.abac.load_policies(),
                firestore_stores.abac.load_policies(),
                sample_size,
            )
        )
    if "privacy" in domains:
        reports.append(
            _parity_report_list(
                "privacy",
                json_stores.privacy.load_policies(),
                firestore_stores.privacy.load_policies(),
                sample_size,
            )
        )
    if "fleet" in domains:
        reports.append(
            _parity_report_list(
                "fleet",
                json_stores.fleet.load_devices(),
                firestore_stores.fleet.load_devices(),
                sample_size,
            )
        )
    if "workflows" in domains:
        reports.append(
            _parity_report_list(
                "workflows",
                json_stores.workflows.load_workflows(),
                firestore_stores.workflows.load_workflows(),
                sample_size,
            )
        )
    if "workflow_runs" in domains:
        reports.append(
            _parity_report_list(
                "workflow_runs",
                json_stores.workflows.load_workflow_runs(),
                firestore_stores.workflows.load_workflow_runs(),
                sample_size,
            )
        )
    if "data_factory_models" in domains:
        reports.append(
            _parity_report_list(
                "data_factory_models",
                json_stores.data_factory.load_models(),
                firestore_stores.data_factory.load_models(),
                sample_size,
            )
        )
    if "data_factory_jobs" in domains:
        reports.append(
            _parity_report_list(
                "data_factory_jobs",
                json_stores.data_factory.load_training_jobs(),
                firestore_stores.data_factory.load_training_jobs(),
                sample_size,
            )
        )
    if "connectors" in domains:
        reports.append(
            _parity_report_list(
                "connectors",
                json_stores.connectors.load_ocr_connectors(),
                firestore_stores.connectors.load_ocr_connectors(),
                sample_size,
            )
        )
    if "api_keys" in domains:
        reports.append(
            _parity_report_list(
                "api_keys",
                json_stores.api_keys.load_api_keys(),
                firestore_stores.api_keys.load_api_keys(),
                sample_size,
            )
        )
    return reports


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
        "--parity-check",
        action="store_true",
        help="Compare JSON vs Firestore counts and sample hashes.",
    )
    parser.add_argument(
        "--parity-report",
        help="Optional JSON report output path for parity checks.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=5,
        help="Number of sample records per domain for parity checks.",
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

    if args.parity_check:
        reports = _run_parity_checks(
            json_stores=json_stores,
            firestore_stores=firestore_stores,
            domains=domains,
            sample_size=max(args.sample_size, 1),
        )
        for report in reports:
            domain = report["domain"]
            json_count = report["json_count"]
            fs_count = report["firestore_count"]
            mismatch = report["comparison"]["mismatch_count"]
            _maybe_print(
                f"parity:{domain}: json={json_count} firestore={fs_count} "
                f"mismatches={mismatch}"
            )
        if args.parity_report:
            with open(args.parity_report, "w", encoding="utf-8") as handle:
                json.dump(reports, handle, ensure_ascii=True, indent=2)
            _maybe_print(f"parity report written: {args.parity_report}")


if __name__ == "__main__":
    main()
