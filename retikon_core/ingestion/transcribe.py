from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class TranscriptSegment:
    index: int
    start_ms: int
    end_ms: int
    text: str
    language: str | None


def transcribe_audio(path: str, duration_seconds: float) -> list[TranscriptSegment]:
    if _use_real_models():
        return _whisper_transcribe(path)
    return _stub_transcribe(duration_seconds)


def _use_real_models() -> bool:
    return os.getenv("USE_REAL_MODELS") == "1"


def _stub_transcribe(duration_seconds: float) -> list[TranscriptSegment]:
    end_ms = int(duration_seconds * 1000.0)
    return [
        TranscriptSegment(
            index=0,
            start_ms=0,
            end_ms=end_ms,
            text="",
            language=None,
        )
    ]


@lru_cache(maxsize=1)
def _load_whisper_model():
    import whisper

    model_name = os.getenv("WHISPER_MODEL_NAME", "small")
    model_dir = os.getenv("MODEL_DIR", "/app/models")
    return whisper.load_model(model_name, download_root=model_dir)


def _whisper_transcribe(path: str) -> list[TranscriptSegment]:
    model = _load_whisper_model()
    result = model.transcribe(path, fp16=False)
    language = result.get("language")
    segments = result.get("segments", [])
    output: list[TranscriptSegment] = []
    for index, segment in enumerate(segments):
        start_ms = int(float(segment.get("start", 0)) * 1000)
        end_ms = int(float(segment.get("end", 0)) * 1000)
        text = str(segment.get("text", "")).strip()
        output.append(
            TranscriptSegment(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                text=text,
                language=language,
            )
        )
    return output
