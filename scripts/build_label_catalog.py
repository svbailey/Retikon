#!/usr/bin/env python3
"""Build a compact, ASCII-only label catalog for CLIP-style scoring.

Sources (primary):
- Open Images V7 boxable classes
- Places365 scene categories
- Kinetics-400 action labels (from train.csv)
"""
from __future__ import annotations

import csv
import io
import sys
import unicodedata
import urllib.request
from pathlib import Path

OPEN_IMAGES_URL = (
    "https://storage.googleapis.com/openimages/v7/"
    "oidv7-class-descriptions-boxable.csv"
)
PLACES365_URL = (
    "https://raw.githubusercontent.com/zhoubolei/places_devkit/master/"
    "categories_places365.txt"
)
KINETICS_TRAIN_URL = "https://s3.amazonaws.com/kinetics/400/annotations/train.csv"

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "retikon_core" / "labels"
OUT_PATH = OUT_DIR / "label_catalog.csv"


def _fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "retikon-label-fetch/1.0",
            "Accept": "text/plain,*/*",
        },
    )
    with urllib.request.urlopen(request) as response:
        raw = response.read()
    return raw.decode("utf-8")


def _normalize_ascii(text: str) -> str:
    text = text.strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.split())


def _parse_open_images() -> list[dict[str, str]]:
    text = _fetch_text(OPEN_IMAGES_URL)
    reader = csv.reader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for row in reader:
        if len(row) < 2:
            continue
        source_id = row[0].strip()
        label = _normalize_ascii(row[1])
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "category": "object",
                "source": "openimages_boxable_v7",
                "source_id": source_id,
            }
        )
    return rows


def _parse_places365() -> list[dict[str, str]]:
    text = _fetch_text(PLACES365_URL)
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        raw_label = " ".join(parts[:-1])
        if raw_label.startswith("/"):
            raw_label = raw_label[1:]
        if len(raw_label) > 2 and raw_label[1] == "/" and raw_label[0].isalpha():
            raw_label = raw_label[2:]
        label = _normalize_ascii(raw_label.replace("_", " ").replace("/", " / "))
        if not label:
            continue
        rows.append(
            {
                "label": label,
                "category": "scene",
                "source": "places365",
                "source_id": parts[-1],
            }
        )
    return rows


def _parse_kinetics() -> list[dict[str, str]]:
    text = _fetch_text(KINETICS_TRAIN_URL)
    reader = csv.reader(io.StringIO(text))
    header = next(reader, None)
    label_index = -1
    if header:
        for idx, name in enumerate(header):
            if name.strip().lower() == "label":
                label_index = idx
                break
    labels: set[str] = set()
    for row in reader:
        if not row:
            continue
        label_raw = row[label_index] if label_index != -1 else row[-1]
        label = _normalize_ascii(label_raw)
        if label:
            labels.add(label)
    rows = [
        {
            "label": label,
            "category": "action",
            "source": "kinetics_400",
            "source_id": "",
        }
        for label in sorted(labels)
    ]
    return rows


def _dedupe(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    output: list[dict[str, str]] = []
    for row in rows:
        key = (row["category"], row["label"])
        if key in seen:
            continue
        seen.add(key)
        output.append(row)
    return output


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    rows.extend(_parse_open_images())
    rows.extend(_parse_places365())
    rows.extend(_parse_kinetics())
    rows = _dedupe(rows)

    with OUT_PATH.open("w", newline="", encoding="ascii") as handle:
        writer = csv.writer(handle)
        writer.writerow(["label", "category", "source", "source_id"])
        for row in rows:
            writer.writerow(
                [row["label"], row["category"], row["source"], row["source_id"]]
            )

    print(f"Wrote {len(rows)} labels to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
