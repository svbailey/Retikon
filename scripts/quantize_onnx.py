from __future__ import annotations

import argparse
import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _require_onnxruntime() -> None:
    try:
        from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "onnxruntime is required to quantize ONNX models. "
            "Install with: pip install onnxruntime"
        ) from exc


def _quantize(input_path: Path, output_path: Path) -> None:
    from onnxruntime.quantization import QuantType, quantize_dynamic

    output_path.parent.mkdir(parents=True, exist_ok=True)
    quantize_dynamic(
        model_input=input_path.as_posix(),
        model_output=output_path.as_posix(),
        weight_type=QuantType.QInt8,
    )


def _check_exists(path: Path) -> None:
    if not path.exists():
        raise SystemExit(
            f"Missing ONNX model: {path}. "
            "Run scripts/export_onnx.py first."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Quantize ONNX text encoders (INT8)."
    )
    parser.add_argument("--all", action="store_true", help="Quantize all text models.")
    parser.add_argument("--text", action="store_true", help="Quantize BGE text.")
    parser.add_argument(
        "--clip-text", action="store_true", help="Quantize CLIP text."
    )
    parser.add_argument(
        "--reranker", action="store_true", help="Quantize reranker model."
    )
    parser.add_argument(
        "--input-dir",
        default="",
        help="Input directory (defaults to MODEL_DIR/onnx).",
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory (defaults to MODEL_DIR/onnx-quant).",
    )
    args = parser.parse_args()

    _require_onnxruntime()

    model_dir = _env("MODEL_DIR", "/app/models")
    input_dir = Path(args.input_dir) if args.input_dir else Path(model_dir) / "onnx"
    output_dir = (
        Path(args.output_dir) if args.output_dir else Path(model_dir) / "onnx-quant"
    )

    quant_all = args.all or not any([args.text, args.clip_text, args.reranker])

    if quant_all or args.text:
        source = input_dir / "bge-text.onnx"
        target = output_dir / "bge-text-int8.onnx"
        _check_exists(source)
        print(f"Quantizing {source} -> {target}")
        _quantize(source, target)

    if quant_all or args.clip_text:
        source = input_dir / "clip-text.onnx"
        target = output_dir / "clip-text-int8.onnx"
        _check_exists(source)
        print(f"Quantizing {source} -> {target}")
        _quantize(source, target)

    if args.reranker:
        source = input_dir / "reranker.onnx"
        target = output_dir / "reranker-int8.onnx"
        _check_exists(source)
        print(f"Quantizing {source} -> {target}")
        _quantize(source, target)


if __name__ == "__main__":
    main()
