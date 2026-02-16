from __future__ import annotations

import argparse
import json
import math
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw


DOC_TEMPLATES = {
    "doc.txt": "Eval token: {token}\nThis is the alpha doc for {token}.\n",
    "table.csv": "id,text\n1,Eval token {token} appears here\n2,Alpha row for {token}\n",
    "sheet.tsv": "id\tvalue\n1\tEval token {token}\n2\tBeta row for {token}\n",
}


def _write_text_assets(target_dir: Path, token: str) -> list[Path]:
    paths: list[Path] = []
    for name, template in DOC_TEMPLATES.items():
        path = target_dir / f"{token}-{name}"
        path.write_text(template.format(token=token), encoding="ascii")
        paths.append(path)
    return paths


def _write_image(path: Path, token: str, fmt: str) -> None:
    image = Image.new("RGB", (512, 512), color=(250, 250, 250))
    draw = ImageDraw.Draw(image)
    draw.rectangle((24, 24, 488, 488), outline=(20, 20, 20), width=2)
    draw.text((40, 60), "RETIKON EVAL", fill=(20, 20, 20))
    draw.text((40, 120), token, fill=(20, 20, 20))
    draw.text((40, 180), "image query", fill=(20, 20, 20))
    image.save(path, format=fmt)


def _write_audio(path: Path, token: str) -> None:
    sample_rate = 16000
    duration_s = 1.2
    frequency = 440.0
    amplitude = 0.3
    frames = int(sample_rate * duration_s)
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        for i in range(frames):
            value = amplitude * math.sin(2 * math.pi * frequency * (i / sample_rate))
            sample = int(value * 32767.0)
            handle.writeframes(sample.to_bytes(2, byteorder="little", signed=True))
        tag = f"eval-{token}".encode("ascii")
        handle.writeframes(tag)


def _write_video(image_path: Path, video_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-loop",
        "1",
        "-t",
        "2",
        "-i",
        str(image_path),
        "-vf",
        "format=yuv420p",
        "-movflags",
        "faststart",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _iter_assets(asset_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(asset_dir.rglob("*"))
        if path.is_file()
    ]


def _classify(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".csv", ".tsv"}:
        return "docs"
    if ext in {".jpg", ".jpeg", ".png"}:
        return "images"
    if ext in {".wav"}:
        return "audio"
    if ext in {".mp4"}:
        return "videos"
    raise ValueError(f"Unsupported eval asset extension: {ext}")


def _expected_uri(
    *,
    bucket: str,
    prefix: str,
    run_id: str,
    idx: int,
    path: Path,
) -> str:
    category = _classify(path)
    return f"gs://{bucket}/{prefix}/{category}/{run_id}/{idx}-{path.name}"


def _write_queries(
    *,
    eval_dir: Path,
    assets: list[Path],
    bucket: str,
    prefix: str,
    run_id: str,
    token: str,
) -> None:
    lines: list[str] = []
    for idx, path in enumerate(assets):
        expected_uri = _expected_uri(
            bucket=bucket,
            prefix=prefix,
            run_id=run_id,
            idx=idx,
            path=path,
        )
        if path.suffix.lower() in {".txt"}:
            payload = {
                "id": "docs-txt-1",
                "modality": "docs",
                "mode": "text",
                "search_type": "vector",
                "query_text": f"Eval token {token} alpha doc",
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".csv"}:
            payload = {
                "id": "docs-csv-1",
                "modality": "docs",
                "mode": "text",
                "search_type": "vector",
                "query_text": f"Eval token {token} appears here",
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".tsv"}:
            payload = {
                "id": "docs-tsv-1",
                "modality": "docs",
                "mode": "text",
                "search_type": "vector",
                "query_text": f"Eval token {token} beta row",
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".png"}:
            payload = {
                "id": "images-png-1",
                "modality": "images",
                "mode": "image",
                "search_type": "vector",
                "image_path": str(path),
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".jpg", ".jpeg"}:
            payload = {
                "id": "images-jpg-1",
                "modality": "images",
                "mode": "image",
                "search_type": "vector",
                "image_path": str(path),
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".wav"}:
            payload = {
                "id": "audio-wav-1",
                "modality": "audio",
                "search_type": "metadata",
                "metadata_filters": {"uri": f"{token}-tone.wav"},
                "expected_uris": [expected_uri],
            }
        elif path.suffix.lower() in {".mp4"}:
            payload = {
                "id": "video-mp4-1",
                "modality": "videos",
                "search_type": "metadata",
                "metadata_filters": {"uri": f"{token}-clip.mp4"},
                "expected_uris": [expected_uri],
            }
        else:
            continue
        lines.append(json.dumps(payload, ensure_ascii=True))

    (eval_dir / "queries.jsonl").write_text("\n".join(lines) + "\n", encoding="ascii")


def _write_metadata(eval_dir: Path, run_id: str, bucket: str, prefix: str) -> None:
    metadata = {"run_id": run_id, "bucket": bucket, "prefix": prefix}
    (eval_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2),
        encoding="ascii",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate unique eval assets.")
    parser.add_argument("--run-id", required=True, help="Eval run id token.")
    parser.add_argument(
        "--eval-dir",
        default="tests/fixtures/eval",
        help="Eval directory to write queries/metadata.",
    )
    parser.add_argument(
        "--asset-root",
        default="tests/fixtures/eval/assets",
        help="Root directory for generated assets.",
    )
    parser.add_argument(
        "--bucket",
        default="retikon-raw-simitor-staging",
        help="Raw bucket for expected URIs.",
    )
    parser.add_argument("--prefix", default="raw_clean", help="Raw prefix.")
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir)
    asset_root = Path(args.asset_root)
    token = args.run_id
    asset_dir = asset_root / token
    asset_dir.mkdir(parents=True, exist_ok=True)

    _write_text_assets(asset_dir, token)

    png_path = asset_dir / f"{token}-image.png"
    jpg_path = asset_dir / f"{token}-image.jpg"
    _write_image(png_path, token, "PNG")
    _write_image(jpg_path, token, "JPEG")

    wav_path = asset_dir / f"{token}-tone.wav"
    _write_audio(wav_path, token)

    mp4_path = asset_dir / f"{token}-clip.mp4"
    _write_video(png_path, mp4_path)

    assets = _iter_assets(asset_dir)
    _write_queries(
        eval_dir=eval_dir,
        assets=assets,
        bucket=args.bucket,
        prefix=args.prefix,
        run_id=args.run_id,
        token=token,
    )
    _write_metadata(eval_dir, args.run_id, args.bucket, args.prefix)

    print(json.dumps({"run_id": args.run_id, "assets": len(assets)}, indent=2))


if __name__ == "__main__":
    main()
