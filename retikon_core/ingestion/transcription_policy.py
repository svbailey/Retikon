from __future__ import annotations

from dataclasses import dataclass

from retikon_core.config import Config
from retikon_core.ingestion.types import IngestSource


@dataclass(frozen=True)
class TranscribePolicy:
    max_ms: int
    source: str | None
    plan_id: str | None


def resolve_transcribe_policy(
    config: Config,
    source: IngestSource | None,
) -> TranscribePolicy:
    plan_id = _resolve_plan_id(source, config)
    limit = config.transcribe_max_ms
    source_label = "global" if limit > 0 else None

    org_limit = None
    if source and source.org_id:
        org_limit = config.transcribe_max_ms_by_org.get(source.org_id)
    plan_limit = None
    if plan_id:
        plan_limit = config.transcribe_max_ms_by_plan.get(plan_id)

    for candidate, label in (
        (org_limit, "org"),
        (plan_limit, "plan"),
    ):
        if candidate and candidate > 0 and (limit <= 0 or candidate < limit):
            limit = candidate
            source_label = label

    return TranscribePolicy(max_ms=limit, source=source_label, plan_id=plan_id)


def transcribe_limit_reason(policy_source: str | None) -> str:
    if policy_source == "org":
        return "transcribe_org_limit_exceeded"
    if policy_source == "plan":
        return "transcribe_plan_limit_exceeded"
    return "transcribe_max_ms_exceeded"


def _resolve_plan_id(source: IngestSource | None, config: Config) -> str | None:
    if source is None or not source.metadata:
        return None
    if not config.transcribe_plan_metadata_keys:
        return None
    metadata = {str(k).strip().lower(): str(v).strip() for k, v in source.metadata.items() if v is not None}
    for key in config.transcribe_plan_metadata_keys:
        value = metadata.get(key)
        if value:
            return value
    return None
