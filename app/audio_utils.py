"""Audio analysis utilities — VAD, duration detection, etc."""
import json
import struct
import subprocess
import wave
from pathlib import Path


def detect_speech_segments(audio_path: Path, min_silence_ms: int = 400,
                           energy_threshold: float = 0.01) -> list:
    """Detect actual speech segments from audio using energy-based VAD.
    Returns list of (start_seconds, end_seconds).
    """
    # Convert to 16kHz mono WAV for analysis
    tmp_path = audio_path.parent / "vad_16k.wav"
    subprocess.run([
        "ffmpeg", "-i", str(audio_path),
        "-ar", "16000", "-ac", "1", "-acodec", "pcm_s16le",
        str(tmp_path), "-y"
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    with wave.open(str(tmp_path), 'rb') as wf:
        sample_rate = wf.getframerate()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    samples = struct.unpack(f"<{n_frames}h", raw)

    window_ms = 20
    window_samples = sample_rate * window_ms // 1000
    min_silence_windows = min_silence_ms // window_ms

    max_val = max(abs(s) for s in samples) or 1
    normalized = [abs(s) / max_val for s in samples]

    is_speech = []
    for i in range(0, len(normalized), window_samples):
        chunk = normalized[i:i + window_samples]
        if chunk:
            rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5
            is_speech.append(rms > energy_threshold)
        else:
            is_speech.append(False)

    segments = []
    in_speech = False
    speech_start = 0
    silence_count = 0

    for i, speaking in enumerate(is_speech):
        if speaking:
            if not in_speech:
                speech_start = i
                in_speech = True
            silence_count = 0
        else:
            if in_speech:
                silence_count += 1
                if silence_count >= min_silence_windows:
                    speech_end = i - silence_count
                    start_sec = speech_start * window_ms / 1000
                    end_sec = speech_end * window_ms / 1000
                    if end_sec - start_sec >= 0.3:
                        segments.append((start_sec, end_sec))
                    in_speech = False
                    silence_count = 0

    if in_speech:
        end_sec = len(is_speech) * window_ms / 1000
        start_sec = speech_start * window_ms / 1000
        if end_sec - start_sec >= 0.3:
            segments.append((start_sec, end_sec))

    # Clean up temp file
    tmp_path.unlink(missing_ok=True)

    return segments


async def get_audio_duration(audio_path: Path) -> float:
    """Get audio duration in seconds using ffprobe."""
    import asyncio
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(audio_path)
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    stdout, _ = await proc.communicate()
    try:
        info = json.loads(stdout)
        return float(info["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0
