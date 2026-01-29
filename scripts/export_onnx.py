from __future__ import annotations

import argparse
import math
import os
from contextlib import contextmanager
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def _require_onnx() -> None:
    try:
        import onnx  # type: ignore[import-untyped]

        _ = onnx
    except ImportError as exc:
        raise SystemExit(
            "onnx is required to export ONNX models. "
            "Install with: pip install onnx"
        ) from exc


def _disable_sdpa() -> None:
    try:
        import torch

        if hasattr(torch.backends, "cuda") and hasattr(
            torch.backends.cuda, "enable_flash_sdp"
        ):
            torch.backends.cuda.enable_flash_sdp(False)
            torch.backends.cuda.enable_mem_efficient_sdp(False)
            torch.backends.cuda.enable_math_sdp(True)
    except Exception:
        return


def _eager_sdpa(
    query,
    key,
    value,
    attn_mask=None,
    dropout_p=0.0,
    is_causal=False,
    scale=None,
):
    import torch

    if scale is None:
        scale = 1.0 / math.sqrt(query.size(-1))
    scores = torch.matmul(query, key.transpose(-2, -1)) * scale
    if attn_mask is not None:
        scores = scores + attn_mask
    if is_causal:
        seq_len = scores.size(-1)
        causal_mask = torch.triu(
            torch.ones(seq_len, seq_len, device=scores.device, dtype=torch.bool),
            diagonal=1,
        )
        scores = scores.masked_fill(causal_mask, float("-inf"))
    weights = torch.softmax(scores, dim=-1)
    if dropout_p and dropout_p > 0:
        weights = torch.nn.functional.dropout(weights, p=dropout_p)
    return torch.matmul(weights, value)


@contextmanager
def _patch_sdpa():
    import torch.nn.functional as F

    original = getattr(F, "scaled_dot_product_attention", None)
    if original is None:
        yield
        return
    F.scaled_dot_product_attention = _eager_sdpa
    try:
        yield
    finally:
        F.scaled_dot_product_attention = original


def _force_eager_attention(config) -> None:
    if hasattr(config, "attn_implementation"):
        config.attn_implementation = "eager"
    if hasattr(config, "text_config") and hasattr(
        config.text_config, "attn_implementation"
    ):
        config.text_config.attn_implementation = "eager"
    if hasattr(config, "vision_config") and hasattr(
        config.vision_config, "attn_implementation"
    ):
        config.vision_config.attn_implementation = "eager"
    if hasattr(config, "audio_config") and hasattr(
        config.audio_config, "attn_implementation"
    ):
        config.audio_config.attn_implementation = "eager"


def _dynamic_axes_text() -> dict[str, dict[int, str]]:
    return {
        "input_ids": {0: "batch", 1: "sequence"},
        "attention_mask": {0: "batch", 1: "sequence"},
        "embeddings": {0: "batch"},
    }


def _dynamic_axes_audio(
    input_features, attention_mask, is_longer
) -> dict[str, dict[int, str]]:
    axes: dict[str, dict[int, str]] = {
        "input_features": {0: "batch"},
        "embeddings": {0: "batch"},
    }
    if input_features.dim() == 3:
        axes["input_features"][1] = "frames"
    elif input_features.dim() == 4:
        axes["input_features"][2] = "frames"
    if attention_mask is not None:
        axes["attention_mask"] = {0: "batch"}
        if attention_mask.dim() == 2:
            axes["attention_mask"][1] = "frames"
        elif attention_mask.dim() == 3:
            axes["attention_mask"][2] = "frames"
    if is_longer is not None:
        axes["is_longer"] = {0: "batch"}
    return axes


def _export_text_bge(model_name: str, cache_dir: str, output_path: Path) -> None:
    import torch
    from transformers import AutoModel, AutoTokenizer

    _disable_sdpa()
    with _patch_sdpa():
        tokenizer = AutoTokenizer.from_pretrained(model_name, cache_dir=cache_dir)
        model = AutoModel.from_pretrained(model_name, cache_dir=cache_dir)
        model.eval()

    class BgeWrapper(torch.nn.Module):
        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, input_ids, attention_mask):
            outputs = self.backbone(
                input_ids=input_ids, attention_mask=attention_mask
            )
            last_hidden = outputs.last_hidden_state
            mask = attention_mask.unsqueeze(-1).to(last_hidden.dtype)
            summed = (last_hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            pooled = summed / counts
            return torch.nn.functional.normalize(pooled, p=2, dim=-1)

    dummy = tokenizer("Retikon ONNX export", return_tensors="pt", padding=True)
    wrapper = BgeWrapper(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _patch_sdpa():
        torch.onnx.export(
            wrapper,
            (dummy["input_ids"], dummy["attention_mask"]),
            output_path.as_posix(),
            input_names=["input_ids", "attention_mask"],
            output_names=["embeddings"],
            dynamic_axes=_dynamic_axes_text(),
            opset_version=17,
            do_constant_folding=True,
        )


def _export_clip_text(model_name: str, cache_dir: str, output_path: Path) -> None:
    import torch
    from transformers import AutoConfig, CLIPModel, CLIPProcessor

    _disable_sdpa()
    with _patch_sdpa():
        config = AutoConfig.from_pretrained(model_name, cache_dir=cache_dir)
        _force_eager_attention(config)
        processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model = CLIPModel.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            config=config,
        )
        model.eval()

    class ClipTextWrapper(torch.nn.Module):
        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, input_ids, attention_mask):
            features = self.backbone.get_text_features(
                input_ids=input_ids, attention_mask=attention_mask
            )
            return torch.nn.functional.normalize(features, p=2, dim=-1)

    dummy = processor(
        text=["Retikon ONNX export"], return_tensors="pt", padding=True
    )
    wrapper = ClipTextWrapper(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _patch_sdpa():
        torch.onnx.export(
            wrapper,
            (dummy["input_ids"], dummy["attention_mask"]),
            output_path.as_posix(),
            input_names=["input_ids", "attention_mask"],
            output_names=["embeddings"],
            dynamic_axes=_dynamic_axes_text(),
            opset_version=17,
            do_constant_folding=True,
        )


def _export_clip_image(model_name: str, cache_dir: str, output_path: Path) -> None:
    import torch
    from PIL import Image
    from transformers import AutoConfig, CLIPModel, CLIPProcessor

    _disable_sdpa()
    with _patch_sdpa():
        config = AutoConfig.from_pretrained(model_name, cache_dir=cache_dir)
        _force_eager_attention(config)
        processor = CLIPProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model = CLIPModel.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            config=config,
        )
        model.eval()

    class ClipImageWrapper(torch.nn.Module):
        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, pixel_values):
            features = self.backbone.get_image_features(pixel_values=pixel_values)
            return torch.nn.functional.normalize(features, p=2, dim=-1)

    dummy_image = Image.new("RGB", (224, 224), color=(0, 0, 0))
    dummy = processor(images=[dummy_image], return_tensors="pt")
    wrapper = ClipImageWrapper(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _patch_sdpa():
        torch.onnx.export(
            wrapper,
            (dummy["pixel_values"],),
            output_path.as_posix(),
            input_names=["pixel_values"],
            output_names=["embeddings"],
            dynamic_axes={
                "pixel_values": {0: "batch"},
                "embeddings": {0: "batch"},
            },
            opset_version=17,
            do_constant_folding=True,
        )


def _export_clap_audio(model_name: str, cache_dir: str, output_path: Path) -> None:
    import numpy as np
    import torch
    from transformers import AutoConfig, ClapModel, ClapProcessor

    _disable_sdpa()
    with _patch_sdpa():
        config = AutoConfig.from_pretrained(model_name, cache_dir=cache_dir)
        _force_eager_attention(config)
        processor = ClapProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model = ClapModel.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            config=config,
        )
        model.eval()

    class ClapAudioWrapper(torch.nn.Module):
        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, input_features, attention_mask=None, is_longer=None):
            if attention_mask is None:
                features = self.backbone.get_audio_features(
                    input_features=input_features,
                    is_longer=is_longer,
                )
            else:
                features = self.backbone.get_audio_features(
                    input_features=input_features,
                    attention_mask=attention_mask,
                    is_longer=is_longer,
                )
            return torch.nn.functional.normalize(features, p=2, dim=-1)

    sample_rate = 48000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    audio = (0.1 * np.sin(2.0 * math.pi * 440.0 * t)).astype("float32")
    dummy = processor(
        audios=[audio],
        sampling_rate=sample_rate,
        return_tensors="pt",
        padding=True,
    )
    input_features = dummy["input_features"]
    attention_mask = dummy.get("attention_mask")
    is_longer = dummy.get("is_longer")
    if is_longer is None:
        is_longer = torch.zeros(
            input_features.shape[0],
            dtype=torch.bool,
        )
    wrapper = ClapAudioWrapper(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    args = (input_features, attention_mask, is_longer)
    input_names = ["input_features"]
    if attention_mask is not None:
        input_names.append("attention_mask")
    input_names.append("is_longer")
    with _patch_sdpa():
        torch.onnx.export(
            wrapper,
            args,
            output_path.as_posix(),
            input_names=input_names,
            output_names=["embeddings"],
            dynamic_axes=_dynamic_axes_audio(
                input_features,
                attention_mask,
                is_longer,
            ),
            opset_version=17,
            do_constant_folding=True,
        )


def _export_clap_text(model_name: str, cache_dir: str, output_path: Path) -> None:
    import torch
    from transformers import AutoConfig, ClapModel, ClapProcessor

    _disable_sdpa()
    with _patch_sdpa():
        config = AutoConfig.from_pretrained(model_name, cache_dir=cache_dir)
        _force_eager_attention(config)
        processor = ClapProcessor.from_pretrained(model_name, cache_dir=cache_dir)
        model = ClapModel.from_pretrained(
            model_name,
            cache_dir=cache_dir,
            config=config,
        )
        model.eval()

    class ClapTextWrapper(torch.nn.Module):
        def __init__(self, backbone) -> None:
            super().__init__()
            self.backbone = backbone

        def forward(self, input_ids, attention_mask):
            features = self.backbone.get_text_features(
                input_ids=input_ids, attention_mask=attention_mask
            )
            return torch.nn.functional.normalize(features, p=2, dim=-1)

    dummy = processor(
        text=["Retikon ONNX export"], return_tensors="pt", padding=True
    )
    wrapper = ClapTextWrapper(model)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with _patch_sdpa():
        torch.onnx.export(
            wrapper,
            (dummy["input_ids"], dummy["attention_mask"]),
            output_path.as_posix(),
            input_names=["input_ids", "attention_mask"],
            output_names=["embeddings"],
            dynamic_axes=_dynamic_axes_text(),
            opset_version=17,
            do_constant_folding=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Export ONNX embedding models.")
    parser.add_argument("--all", action="store_true", help="Export all models.")
    parser.add_argument("--text", action="store_true", help="Export BGE text.")
    parser.add_argument(
        "--clip-text", action="store_true", help="Export CLIP text."
    )
    parser.add_argument(
        "--clip-image", action="store_true", help="Export CLIP image."
    )
    parser.add_argument(
        "--clap-audio", action="store_true", help="Export CLAP audio."
    )
    parser.add_argument(
        "--clap-text", action="store_true", help="Export CLAP text."
    )
    parser.add_argument(
        "--output-dir",
        default="",
        help="Output directory (defaults to MODEL_DIR/onnx).",
    )
    args = parser.parse_args()

    _require_onnx()

    model_dir = _env("MODEL_DIR", "/app/models")
    text_model = _env("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")
    image_model = _env("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")
    audio_model = _env("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")

    output_dir = Path(args.output_dir) if args.output_dir else Path(model_dir) / "onnx"
    output_dir.mkdir(parents=True, exist_ok=True)

    export_all = args.all or not any(
        [
            args.text,
            args.clip_text,
            args.clip_image,
            args.clap_audio,
            args.clap_text,
        ]
    )

    if export_all or args.text:
        print(f"Exporting BGE text ONNX to {output_dir}")
        _export_text_bge(text_model, model_dir, output_dir / "bge-text.onnx")
    if export_all or args.clip_text:
        print(f"Exporting CLIP text ONNX to {output_dir}")
        _export_clip_text(image_model, model_dir, output_dir / "clip-text.onnx")
    if export_all or args.clip_image:
        print(f"Exporting CLIP image ONNX to {output_dir}")
        _export_clip_image(image_model, model_dir, output_dir / "clip-image.onnx")
    if export_all or args.clap_audio:
        print(f"Exporting CLAP audio ONNX to {output_dir}")
        _export_clap_audio(audio_model, model_dir, output_dir / "clap-audio.onnx")
    if export_all or args.clap_text:
        print(f"Exporting CLAP text ONNX to {output_dir}")
        _export_clap_text(audio_model, model_dir, output_dir / "clap-text.onnx")


if __name__ == "__main__":
    main()
