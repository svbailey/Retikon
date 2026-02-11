from __future__ import annotations

import audioop
import json
import math
import re
import shutil
import subprocess
import tempfile
import wave
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


@dataclass(frozen=True)
class FrameInfo:
    path: str
    timestamp_ms: int


@dataclass(frozen=True)
class AudioAnalysis:
    duration_ms: int
    speech_ms: int
    silence_ms: int
    has_speech: bool


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


def analyze_audio(
    path: str,
    *,
    frame_ms: int = 30,
    silence_db: float = -45.0,
    min_speech_ms: int = 300,
) -> AudioAnalysis:
    with wave.open(path, "rb") as handle:
        sample_rate = handle.getframerate()
        channels = handle.getnchannels()
        sample_width = handle.getsampwidth()
        total_frames = handle.getnframes()
        duration_ms = int((total_frames / float(sample_rate)) * 1000.0)
        frames_per_chunk = max(1, int(sample_rate * frame_ms / 1000))
        bytes_per_frame = channels * sample_width
        max_possible = float(1 << (8 * sample_width - 1))
        speech_ms = 0
        silence_ms = 0
        while True:
            chunk = handle.readframes(frames_per_chunk)
            if not chunk:
                break
            frame_count = len(chunk) // bytes_per_frame
            if frame_count <= 0:
                continue
            chunk_ms = int((frame_count / float(sample_rate)) * 1000.0)
            rms = audioop.rms(chunk, sample_width) if chunk else 0
            if rms <= 0:
                db = -float("inf")
            else:
                db = 20.0 * math.log10(rms / max_possible)
            if db >= silence_db:
                speech_ms += chunk_ms
            else:
                silence_ms += chunk_ms
        remainder = max(0, duration_ms - speech_ms - silence_ms)
        silence_ms += remainder
        has_speech = speech_ms >= max(1, min_speech_ms)
        return AudioAnalysis(
            duration_ms=duration_ms,
            speech_ms=speech_ms,
            silence_ms=silence_ms,
            has_speech=has_speech,
        )


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
        f"fps={safe_fps},format=yuvj420p",
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


_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\\.[0-9]+)?)")


def _parse_pts_times(stderr: str) -> list[float]:
    times: list[float] = []
    for line in stderr.splitlines():
        if "showinfo" not in line or "pts_time" not in line:
            continue
        match = _PTS_TIME_RE.search(line)
        if not match:
            continue
        try:
            times.append(float(match.group(1)))
        except ValueError:
            continue
    return times


def _extract_scene_frames(
    input_path: str,
    output_dir: str,
    scene_threshold: float,
    fallback_fps: float,
) -> list[FrameInfo]:
    _ensure_tool("ffmpeg")
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    output_pattern = Path(output_dir) / "scene-%05d.jpg"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        f"select='gt(scene,{scene_threshold})',format=yuvj420p,showinfo",
        "-vsync",
        "vfr",
        str(output_pattern),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        _raise_media_error(
            "ffmpeg extract keyframes",
            exc.stderr or exc.stdout or str(exc),
        )
    timestamps = _parse_pts_times(result.stderr or "")
    frames = sorted(Path(output_dir).glob("scene-*.jpg"))
    infos: list[FrameInfo] = []
    for idx, frame in enumerate(frames):
        if idx < len(timestamps):
            timestamp_ms = int(timestamps[idx] * 1000.0)
        else:
            timestamp_ms = frame_timestamp_ms(idx, fallback_fps)
        infos.append(FrameInfo(path=str(frame), timestamp_ms=timestamp_ms))
    return infos


def extract_keyframes(
    input_path: str,
    output_dir: str,
    scene_threshold: float,
    min_frames: int,
    fallback_fps: float,
) -> list[FrameInfo]:
    try:
        scene_frames = _extract_scene_frames(
            input_path=input_path,
            output_dir=output_dir,
            scene_threshold=scene_threshold,
            fallback_fps=fallback_fps,
        )
    except RecoverableError:
        scene_frames = []

    if len(scene_frames) >= min_frames:
        return scene_frames

    for frame in Path(output_dir).glob("scene-*.jpg"):
        frame.unlink(missing_ok=True)

    frame_paths = extract_frames(input_path, fallback_fps, output_dir)
    return [
        FrameInfo(path=path, timestamp_ms=frame_timestamp_ms(idx, fallback_fps))
        for idx, path in enumerate(frame_paths)
    ]


def frame_timestamp_ms(index: int, fps: float) -> int:
    if fps <= 0:
        return 0
    return int(math.floor((index / fps) * 1000.0))
