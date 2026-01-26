#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from typing import Iterable

from google.cloud import pubsub_v1


def _subscription_path(
    client: pubsub_v1.SubscriberClient, project: str, sub: str
) -> str:
    if sub.startswith("projects/"):
        return sub
    return client.subscription_path(project, sub)


def _topic_path(client: pubsub_v1.PublisherClient, project: str, topic: str) -> str:
    if topic.startswith("projects/"):
        return topic
    return client.topic_path(project, topic)


def _decode_payload(data: bytes) -> dict:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return {"raw": data.decode("utf-8", errors="replace")}


def list_messages(project: str, subscription: str, limit: int) -> None:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = _subscription_path(subscriber, project, subscription)
    response = subscriber.pull(
        request={"subscription": sub_path, "max_messages": limit}
    )
    if not response.received_messages:
        print("No messages.")
        return
    ack_ids = []
    for received in response.received_messages:
        payload = _decode_payload(received.message.data)
        print(
            json.dumps(
                {
                    "message_id": received.message.message_id,
                    "error_code": payload.get("error_code"),
                    "attempt_count": payload.get("attempt_count"),
                    "modality": payload.get("modality"),
                    "object": payload.get("gcs_event", {}).get("name"),
                },
                ensure_ascii=True,
            )
        )
        ack_ids.append(received.ack_id)
    subscriber.modify_ack_deadline(
        request={
            "subscription": sub_path,
            "ack_ids": ack_ids,
            "ack_deadline_seconds": 0,
        }
    )


def pull_messages(project: str, subscription: str, limit: int, ack: bool) -> None:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = _subscription_path(subscriber, project, subscription)
    response = subscriber.pull(
        request={"subscription": sub_path, "max_messages": limit}
    )
    if not response.received_messages:
        print("No messages.")
        return
    ack_ids = []
    for received in response.received_messages:
        payload = _decode_payload(received.message.data)
        print(json.dumps(payload, indent=2, ensure_ascii=True))
        ack_ids.append(received.ack_id)
    if ack:
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
    else:
        subscriber.modify_ack_deadline(
            request={
                "subscription": sub_path,
                "ack_ids": ack_ids,
                "ack_deadline_seconds": 0,
            }
        )


def replay_messages(
    project: str,
    subscription: str,
    ingest_url: str,
    limit: int,
    ack: bool,
) -> None:
    subscriber = pubsub_v1.SubscriberClient()
    sub_path = _subscription_path(subscriber, project, subscription)
    response = subscriber.pull(
        request={"subscription": sub_path, "max_messages": limit}
    )
    if not response.received_messages:
        print("No messages.")
        return
    ack_ids = []
    for received in response.received_messages:
        payload = _decode_payload(received.message.data)
        cloudevent = payload.get("cloudevent")
        if not isinstance(cloudevent, dict):
            print("Skipping message without cloudevent payload.")
            ack_ids.append(received.ack_id)
            continue
        req = urllib.request.Request(
            ingest_url,
            data=json.dumps(cloudevent).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status = resp.status
        except Exception as exc:
            print(f"Replay failed: {exc}")
            continue
        print(
            json.dumps(
                {
                    "message_id": received.message.message_id,
                    "status": status,
                },
                ensure_ascii=True,
            )
        )
        ack_ids.append(received.ack_id)
    if ack and ack_ids:
        subscriber.acknowledge(request={"subscription": sub_path, "ack_ids": ack_ids})
    elif ack_ids:
        subscriber.modify_ack_deadline(
            request={
                "subscription": sub_path,
                "ack_ids": ack_ids,
                "ack_deadline_seconds": 0,
            }
        )


def main(argv: Iterable[str]) -> int:
    parser = argparse.ArgumentParser(description="Retikon DLQ helper")
    parser.add_argument("--project", required=True)
    parser.add_argument("--subscription", required=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list", help="List DLQ messages (peek)")
    list_cmd.add_argument("--limit", type=int, default=10)

    pull_cmd = subparsers.add_parser("pull", help="Pull DLQ messages")
    pull_cmd.add_argument("--limit", type=int, default=1)
    pull_cmd.add_argument("--ack", action="store_true")

    replay_cmd = subparsers.add_parser("replay", help="Replay DLQ messages")
    replay_cmd.add_argument("--limit", type=int, default=1)
    replay_cmd.add_argument("--ack", action="store_true")
    replay_cmd.add_argument("--ingest-url", required=True)

    args = parser.parse_args(list(argv))
    if args.command == "list":
        list_messages(args.project, args.subscription, args.limit)
        return 0
    if args.command == "pull":
        pull_messages(args.project, args.subscription, args.limit, args.ack)
        return 0
    if args.command == "replay":
        replay_messages(
            args.project,
            args.subscription,
            args.ingest_url,
            args.limit,
            args.ack,
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
