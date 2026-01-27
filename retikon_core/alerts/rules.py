from __future__ import annotations

from typing import Iterable

from retikon_core.alerts.types import AlertMatch, AlertRule
from retikon_core.webhooks.types import WebhookEvent


def rule_matches(rule: AlertRule, event: WebhookEvent) -> bool:
    if not rule.enabled:
        return False
    if rule.event_types and not _matches_type(rule.event_types, event.event_type):
        return False
    if rule.modalities and (
        not event.modality or event.modality not in rule.modalities
    ):
        return False
    if rule.min_confidence is not None:
        if event.confidence is None or event.confidence < rule.min_confidence:
            return False
    if rule.tags:
        event_tags = set(event.tags or ())
        if not event_tags.intersection(rule.tags):
            return False
    return True


def evaluate_rules(
    event: WebhookEvent,
    rules: Iterable[AlertRule],
) -> list[AlertMatch]:
    matches: list[AlertMatch] = []
    for rule in rules:
        if rule_matches(rule, event):
            matches.append(
                AlertMatch(
                    rule_id=rule.id,
                    event_id=event.id,
                    destinations=rule.destinations,
                )
            )
    return matches


def _matches_type(event_types: tuple[str, ...], event_type: str) -> bool:
    if "*" in event_types:
        return True
    return event_type in event_types
