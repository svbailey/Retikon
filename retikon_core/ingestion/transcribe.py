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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_str(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip()
    return value or default


def _normalize_language(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip().lower()
    return cleaned or None


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


def _detect_language(model, path: str) -> tuple[str | None, float | None]:
    try:
        import whisper

        audio = whisper.load_audio(path)
        if getattr(audio, "size", 0) == 0:
            return None, None
        detect_seconds = _env_float("WHISPER_DETECT_SECONDS", 30.0)
        if detect_seconds > 0:
            max_samples = int(detect_seconds * whisper.audio.SAMPLE_RATE)
            if max_samples > 0:
                audio = audio[:max_samples]
        audio = whisper.pad_or_trim(audio)
        mel = whisper.log_mel_spectrogram(audio).to(model.device)
        _, probs = model.detect_language(mel)
        if not probs:
            return None, None
        language, confidence = max(probs.items(), key=lambda item: item[1])
        return language, float(confidence)
    except Exception:
        return None, None


def _resolve_transcribe_options(
    model,
    path: str,
) -> tuple[str | None, str]:
    forced_language = _normalize_language(_env_str("WHISPER_LANGUAGE"))
    default_language = _normalize_language(_env_str("WHISPER_LANGUAGE_DEFAULT"))
    auto_language = _env_bool("WHISPER_LANGUAGE_AUTO", False)
    min_confidence = _env_float("WHISPER_MIN_CONFIDENCE", 0.6)
    task = (_env_str("WHISPER_TASK", "transcribe") or "transcribe").strip().lower()
    non_english_task = _normalize_language(
        _env_str("WHISPER_NON_ENGLISH_TASK", "translate")
    )

    if forced_language:
        return forced_language, task

    if auto_language:
        detected_language, confidence = _detect_language(model, path)
        if detected_language:
            if default_language:
                if detected_language != default_language and (
                    confidence is None or confidence >= min_confidence
                ):
                    task_override = non_english_task or task
                    return detected_language, task_override
                return default_language, task
            return detected_language, task

    if default_language:
        return default_language, task

    return None, task


def _whisper_transcribe(path: str) -> list[TranscriptSegment]:
    model = _load_whisper_model()
    language, task = _resolve_transcribe_options(model, path)
    result = model.transcribe(
        path,
        fp16=False,
        language=language,
        task=task,
    )
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
