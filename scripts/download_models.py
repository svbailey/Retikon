from __future__ import annotations

import os
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


def main() -> None:
    model_dir = _env("MODEL_DIR", "/app/models")
    text_model = _env("TEXT_MODEL_NAME", "BAAI/bge-base-en-v1.5")
    image_model = _env("IMAGE_MODEL_NAME", "openai/clip-vit-base-patch32")
    audio_model = _env("AUDIO_MODEL_NAME", "laion/clap-htsat-fused")
    whisper_model = _env("WHISPER_MODEL_NAME", "small")
    export_onnx = _env("EXPORT_ONNX", "").strip().lower() in {"1", "true", "yes"}
    quantize_onnx = _env("QUANTIZE_ONNX", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    embedding_backend = _env("EMBEDDING_BACKEND", "").strip().lower()
    text_backend = _env("TEXT_EMBED_BACKEND", "").strip().lower()
    image_backend = _env("IMAGE_EMBED_BACKEND", "").strip().lower()
    audio_backend = _env("AUDIO_EMBED_BACKEND", "").strip().lower()
    image_text_backend = _env("IMAGE_TEXT_EMBED_BACKEND", "").strip().lower()
    audio_text_backend = _env("AUDIO_TEXT_EMBED_BACKEND", "").strip().lower()
    backends = {
        backend
        for backend in (
            embedding_backend,
            text_backend,
            image_backend,
            audio_backend,
            image_text_backend,
            audio_text_backend,
        )
        if backend
    }

    Path(model_dir).mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HOME", model_dir)
    os.environ.setdefault("TRANSFORMERS_CACHE", model_dir)

    print(f"Downloading text model: {text_model}")
    from sentence_transformers import SentenceTransformer

    SentenceTransformer(text_model, cache_folder=model_dir)

    print(f"Downloading CLIP model: {image_model}")
    from transformers import CLIPModel, CLIPProcessor

    CLIPModel.from_pretrained(image_model, cache_dir=model_dir)
    CLIPProcessor.from_pretrained(image_model, cache_dir=model_dir)

    print(f"Downloading CLAP model: {audio_model}")
    from transformers import ClapModel, ClapProcessor

    ClapModel.from_pretrained(audio_model, cache_dir=model_dir)
    ClapProcessor.from_pretrained(audio_model, cache_dir=model_dir)

    print(f"Downloading Whisper model: {whisper_model}")
    import whisper

    whisper.load_model(whisper_model, download_root=model_dir)

    if export_onnx or any(backend in {"onnx", "quantized"} for backend in backends):
        export_script = Path(__file__).with_name("export_onnx.py")
        if export_script.exists():
            print("Exporting ONNX models...")
            import subprocess
            import sys

            subprocess.check_call([sys.executable, export_script.as_posix(), "--all"])
        else:
            raise SystemExit(f"Missing ONNX export script: {export_script}")

    if quantize_onnx or any(backend == "quantized" for backend in backends):
        quantize_script = Path(__file__).with_name("quantize_onnx.py")
        if quantize_script.exists():
            print("Quantizing ONNX models...")
            import subprocess
            import sys

            subprocess.check_call(
                [sys.executable, quantize_script.as_posix(), "--all"]
            )
        else:
            raise SystemExit(f"Missing ONNX quantize script: {quantize_script}")


if __name__ == "__main__":
    main()
