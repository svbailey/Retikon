from __future__ import annotations

import audioop
import io
import math
import wave
from dataclasses import dataclass


@dataclass(frozen=True)
class AudioWindow:
    start_ms: int
    end_ms: int
    audio_bytes: bytes
    rms_db: float


@dataclass(frozen=True)
class AudioWindowBatch:
    windows: list[AudioWindow]
    candidate_count: int
    skipped_silence_count: int


def _db_from_rms(rms: int, max_possible: float) -> float:
    if rms <= 0 or max_possible <= 0:
        return -float("inf")
    return 20.0 * math.log10(rms / max_possible)


def _wav_bytes_from_pcm(
    *,
    chunk: bytes,
    channels: int,
    sample_width: int,
    sample_rate: int,
) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(channels)
        writer.setsampwidth(sample_width)
        writer.setframerate(sample_rate)
        writer.writeframes(chunk)
    return buffer.getvalue()


def extract_audio_windows(
    *,
    path: str,
    window_s: float,
    hop_s: float,
    max_segments: int,
    silence_db: float | None = None,
) -> AudioWindowBatch:
    windows: list[AudioWindow] = []
    candidate_count = 0
    skipped_silence_count = 0

    with wave.open(path, "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        total_frames = handle.getnframes()
        if sample_rate <= 0 or channels <= 0 or sample_width <= 0 or total_frames <= 0:
            return AudioWindowBatch(
                windows=[],
                candidate_count=0,
                skipped_silence_count=0,
            )

        frames_per_window = max(1, int(round(sample_rate * window_s)))
        frames_per_hop = max(1, int(round(sample_rate * hop_s)))
        bytes_per_frame = channels * sample_width
        max_possible = float(1 << (8 * sample_width - 1))

        start_frame = 0
        while start_frame < total_frames and candidate_count < max_segments:
            handle.setpos(start_frame)
            chunk = handle.readframes(frames_per_window)
            frame_count = len(chunk) // bytes_per_frame
            if frame_count <= 0:
                break
            candidate_count += 1
            rms = audioop.rms(chunk, sample_width) if chunk else 0
            rms_db = _db_from_rms(rms, max_possible)
            if silence_db is not None and rms_db < silence_db:
                skipped_silence_count += 1
            else:
                end_frame = min(total_frames, start_frame + frame_count)
                windows.append(
                    AudioWindow(
                        start_ms=int((start_frame / float(sample_rate)) * 1000.0),
                        end_ms=int((end_frame / float(sample_rate)) * 1000.0),
                        audio_bytes=_wav_bytes_from_pcm(
                            chunk=chunk,
                            channels=channels,
                            sample_width=sample_width,
                            sample_rate=sample_rate,
                        ),
                        rms_db=rms_db,
                    )
                )
            start_frame += frames_per_hop

    return AudioWindowBatch(
        windows=windows,
        candidate_count=candidate_count,
        skipped_silence_count=skipped_silence_count,
    )
