from __future__ import annotations

import os
from dataclasses import dataclass


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


def _whisper_transcribe(path: str) -> list[TranscriptSegment]:
    raise RuntimeError("Whisper transcription is not wired yet.")
