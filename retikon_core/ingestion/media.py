from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from retikon_core.errors import PermanentError, RecoverableError


@dataclass(frozen=True)
class MediaProbe:
    duration_seconds: float
    has_audio: bool
    has_video: bool
    audio_sample_rate: int | None
    audio_channels: int | None
    video_width: int | None
    video_height: int | None
    frame_rate: float | None
    frame_count: int | None


def _ensure_tool(name: str) -> None:
    if shutil.which(name) is None:
        raise RecoverableError(f"Missing required binary: {name}")


_CORRUPT_MARKERS = (
    "invalid data found when processing input",
    "moov atom not found",
    "output file does not contain any stream",
    "could not find codec parameters",
    "invalid argument",
    "unknown format",
)


def _raise_media_error(step: str, stderr: str) -> None:
    message = stderr.strip() or "Unknown media error"
    lowered = message.lower()
    if any(marker in lowered for marker in _CORRUPT_MARKERS):
        raise PermanentError(f"{step} failed: {message}")
    raise RecoverableError(f"{step} failed: {message}")


def _parse_fraction(value: str | None) -> float | None:
    if not value:
        return None
    if "/" in value:
        num, den = value.split("/", 1)
        try:
            return float(num) / float(den)
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def probe_media(path: str) -> MediaProbe:
    _ensure_tool("ffprobe")
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        _raise_media_error("ffprobe", exc.stderr or exc.stdout or str(exc))

    payload = json.loads(result.stdout or "{}")
    format_info = payload.get("format", {}) or {}
    streams = payload.get("streams", []) or []

    duration = _parse_fraction(format_info.get("duration")) or 0.0
    has_audio = False
    has_video = False
    audio_rate = None
    audio_channels = None
    video_width = None
    video_height = None
    frame_rate = None
    frame_count = None

    for stream in streams:
        if stream.get("codec_type") == "audio":
            has_audio = True
            audio_rate = _parse_int(stream.get("sample_rate"))
            audio_channels = stream.get("channels")
            stream_duration = _parse_fraction(stream.get("duration"))
            if stream_duration and stream_duration > duration:
                duration = stream_duration
        if stream.get("codec_type") == "video":
            has_video = True
            video_width = stream.get("width")
            video_height = stream.get("height")
            frame_rate = _parse_fraction(stream.get("avg_frame_rate"))
            frame_count = _parse_int(stream.get("nb_frames"))
            stream_duration = _parse_fraction(stream.get("duration"))
            if stream_duration and stream_duration > duration:
                duration = stream_duration

    return MediaProbe(
        duration_seconds=duration,
        has_audio=has_audio,
        has_video=has_video,
        audio_sample_rate=audio_rate,
        audio_channels=audio_channels,
        video_width=video_width,
        video_height=video_height,
        frame_rate=frame_rate,
        frame_count=frame_count,
    )


def normalize_audio(input_path: str, sample_rate: int = 48000) -> str:
    _ensure_tool("ffmpeg")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        tmp_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        _raise_media_error("ffmpeg normalize", exc.stderr or exc.stdout or str(exc))
    return tmp_path


def extract_audio(input_path: str, sample_rate: int = 48000) -> str:
    _ensure_tool("ffmpeg")
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp_path = tmp.name
    tmp.close()

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(sample_rate),
        tmp_path,
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        _raise_media_error(
            "ffmpeg extract audio",
            exc.stderr or exc.stdout or str(exc),
        )
    return tmp_path


def extract_frames(input_path: str, fps: float, output_dir: str) -> list[str]:
    _ensure_tool("ffmpeg")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    safe_fps = max(fps, 0.1)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        f"fps={safe_fps}",
        str(Path(output_dir) / "frame-%05d.jpg"),
    ]
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        _raise_media_error(
            "ffmpeg extract frames",
            exc.stderr or exc.stdout or str(exc),
        )

    frames = sorted(Path(output_dir).glob("frame-*.jpg"))
    return [str(frame) for frame in frames]


def frame_timestamp_ms(index: int, fps: float) -> int:
    if fps <= 0:
        return 0
    return int(math.floor((index / fps) * 1000.0))
