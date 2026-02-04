# Label Catalog

This folder contains a compact, ASCII-only label catalog suitable for
CLIP-style zero-shot scoring in the visual test UI.

Contents
- label_catalog.csv

Sources
- Open Images V7 boxable classes (objects)
- Places365 categories (scenes)
- Kinetics-400 labels (actions)

Build
- python scripts/build_label_catalog.py

Notes
- Labels are normalized to ASCII for repository consistency.
- Duplicates within a category are removed during build.
