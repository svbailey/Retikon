import wave
from pathlib import Path

from retikon_core.ingestion.pipelines.audio_segments import extract_audio_windows


def test_extract_audio_windows_respects_max_segments():
    fixture = Path("tests/fixtures/sample.wav")
    batch = extract_audio_windows(
        path=str(fixture),
        window_s=5.0,
        hop_s=5.0,
        max_segments=1,
        silence_db=None,
    )
    assert batch.candidate_count == 1
    assert len(batch.windows) == 1


def test_extract_audio_windows_silence_gate_filters(tmp_path):
    silent_path = tmp_path / "silent.wav"
    sample_rate = 48000
    with wave.open(str(silent_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(b"\x00\x00" * sample_rate)

    batch = extract_audio_windows(
        path=str(silent_path),
        window_s=0.5,
        hop_s=0.5,
        max_segments=10,
        silence_db=-45.0,
    )
    assert batch.candidate_count > 0
    assert len(batch.windows) == 0
    assert batch.skipped_silence_count == batch.candidate_count
