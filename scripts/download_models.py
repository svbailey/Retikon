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


if __name__ == "__main__":
    main()
