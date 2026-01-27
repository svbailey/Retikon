from __future__ import annotations

from retikon_core.alerts import evaluate_rules, rule_matches
from retikon_core.alerts.types import AlertDestination, AlertRule
from retikon_core.webhooks.types import WebhookEvent


def _rule(**kwargs) -> AlertRule:
    return AlertRule(
        id="rule-1",
        name="Rule",
        event_types=kwargs.get("event_types"),
        modalities=kwargs.get("modalities"),
        min_confidence=kwargs.get("min_confidence"),
        tags=kwargs.get("tags"),
        destinations=kwargs.get("destinations", ()),
        enabled=kwargs.get("enabled", True),
        created_at="now",
        updated_at="now",
    )


def test_rule_matches_filters():
    dest = AlertDestination(kind="webhook", target="wh-1")
    rule = _rule(
        event_types=("asset.detected",),
        modalities=("image",),
        min_confidence=0.8,
        tags=("person",),
        destinations=(dest,),
    )
    event = WebhookEvent(
        id="evt-1",
        event_type="asset.detected",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
        modality="image",
        confidence=0.9,
        tags=("person", "vehicle"),
    )
    assert rule_matches(rule, event)

    low_conf = WebhookEvent(
        id="evt-2",
        event_type="asset.detected",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
        modality="image",
        confidence=0.5,
        tags=("person",),
    )
    assert not rule_matches(rule, low_conf)


def test_evaluate_rules_returns_matches():
    dest = AlertDestination(kind="webhook", target="wh-2")
    rule = _rule(event_types=("*",), destinations=(dest,))
    event = WebhookEvent(
        id="evt-3",
        event_type="alert.triggered",
        created_at="2026-01-27T00:00:00Z",
        payload={"ok": True},
    )
    matches = evaluate_rules(event, [rule])
    assert len(matches) == 1
    assert matches[0].rule_id == rule.id
    assert matches[0].destinations[0].target == "wh-2"
