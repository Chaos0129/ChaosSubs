import asyncio
import json
import subprocess
import time
from pathlib import Path

from app.config import UPLOAD_DIR, WHISPER_MODEL
from app.srt_utils import whisper_segments_to_srt, write_srt, parse_srt, SrtEntry
from app.translate import translate_batch, translate_single

# In-memory job state, shared with main.py
jobs: dict = {}

BATCH_SIZE = 10

# Phase 1: extract + transcribe + translate (weights must sum to 100)
STEP_WEIGHTS = {1: 5, 2: 45, 3: 50}

# Whisper processing speed ratio: estimated_seconds = video_duration * ratio
# Will be calibrated after first real run
WHISPER_SPEED_RATIO = 1.5


async def run_pipeline(job_id: str) -> None:
    """Phase 1: Generate subtitles only (no video burn)."""
    job_dir = UPLOAD_DIR / job_id
    input_video = _find_input_video(job_dir)
    audio_path = job_dir / "audio.wav"
    original_srt = job_dir / "original.srt"
    translated_srt = job_dir / "translated_zh.srt"

    jobs[job_id]["start_time"] = time.time()

    try:
        # Step 1: Extract audio
        _update(job_id, step=1, step_name="提取音频中...", step_progress=0)
        await _extract_audio(input_video, audio_path)
        _update(job_id, step=1, step_progress=100)

        # Get video duration for progress estimation
        duration = await _get_duration(input_video)
        jobs[job_id]["video_duration"] = duration

        # Step 2: Transcribe with Whisper
        _update(job_id, step=2, step_name="语音识别中...", step_progress=0)
        language = jobs[job_id].get("language")
        await _transcribe_with_progress(job_id, audio_path, original_srt, language, duration)
        _update(job_id, step=2, step_progress=100)

        # Step 3: Translate subtitles
        _update(job_id, step=3, step_name="翻译字幕中...", step_progress=0)
        await _translate(job_id, original_srt, translated_srt, language)
        _update(job_id, step=3, step_progress=100)

        _update(job_id, status="done", step_name="字幕生成完成！", overall_progress=100)

    except Exception as e:
        _update(job_id, status="error", error=str(e))


async def run_burn(job_id: str) -> None:
    """Phase 2 (optional): Burn subtitles into video."""
    job_dir = UPLOAD_DIR / job_id
    input_video = _find_input_video(job_dir)
    translated_srt = job_dir / "translated_zh.srt"
    output_video = job_dir / "output.mp4"

    jobs[job_id]["burn_status"] = "processing"
    jobs[job_id]["burn_progress"] = 0

    try:
        await _burn_subtitles(input_video, translated_srt, output_video)
        jobs[job_id]["burn_status"] = "done"
        jobs[job_id]["burn_progress"] = 100
    except Exception as e:
        jobs[job_id]["burn_status"] = "error"
        jobs[job_id]["burn_error"] = str(e)


def _update(job_id: str, **kwargs) -> None:
    if job_id not in jobs:
        return
    jobs[job_id].update(kwargs)

    # Recalculate overall progress
    step = jobs[job_id].get("step", 0)
    step_progress = jobs[job_id].get("step_progress", 0)
    if step > 0:
        done_weight = sum(STEP_WEIGHTS.get(s, 0) for s in range(1, step))
        current_weight = STEP_WEIGHTS.get(step, 0) * step_progress / 100
        overall = int(done_weight + current_weight)
        jobs[job_id]["overall_progress"] = min(100, overall)

    # Estimate remaining time
    start_time = jobs[job_id].get("start_time")
    overall = jobs[job_id].get("overall_progress", 0)
    if start_time and overall > 2:
        elapsed = time.time() - start_time
        estimated_total = elapsed / (overall / 100)
        remaining = max(0, estimated_total - elapsed)
        jobs[job_id]["eta_seconds"] = int(remaining)
    else:
        jobs[job_id]["eta_seconds"] = -1  # unknown


def _find_input_video(job_dir: Path) -> Path:
    """Find the input video file regardless of extension."""
    for f in job_dir.iterdir():
        if f.name.startswith("input.") and f.suffix.lower() in (
            ".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m4v"
        ):
            return f
    raise RuntimeError("找不到输入视频文件")


async def _get_duration(video_path: Path) -> float:
    """Get video duration in seconds using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path)
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


async def _extract_audio(input_video: Path, output_audio: Path) -> None:
    cmd = [
        "ffmpeg", "-i", str(input_video),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(output_audio), "-y"
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    code = await proc.wait()
    if code != 0:
        raise RuntimeError("FFmpeg 音频提取失败")


async def _transcribe_with_progress(
    job_id: str, audio_path: Path, output_srt: Path,
    language: str = None, duration: float = 0.0
) -> None:
    """Run Whisper transcription with simulated progress based on video duration."""
    done_event = asyncio.Event()
    estimated_seconds = max(duration * WHISPER_SPEED_RATIO, 30)  # at least 30s
    whisper_start = time.time()

    async def _fake_progress():
        """Simulate progress: ramp up to 90%, slow down near end."""
        while not done_event.is_set():
            elapsed = time.time() - whisper_start
            # Progress curve: fast at start, slows near 90%
            raw = elapsed / estimated_seconds
            if raw < 0.8:
                pct = raw * 100  # linear up to ~80%
            else:
                # Slow down: asymptotically approach 95%
                pct = 80 + (raw - 0.8) * 75  # slower growth
            pct = min(pct, 95)  # never exceed 95% until actually done
            _update(job_id, step=2, step_progress=int(pct))
            await asyncio.sleep(1)

    # Start fake progress updater
    progress_task = asyncio.create_task(_fake_progress())

    def _run():
        from faster_whisper import WhisperModel
        model = WhisperModel(WHISPER_MODEL, compute_type="int8")
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            word_timestamps=True,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        seg_list = [{"start": s.start, "end": s.end, "text": s.text} for s in segments]
        entries = whisper_segments_to_srt(seg_list)
        write_srt(entries, output_srt)

    try:
        await asyncio.to_thread(_run)
    finally:
        done_event.set()
        progress_task.cancel()
        # Record actual time for future calibration
        actual_time = time.time() - whisper_start
        if duration > 0:
            jobs[job_id]["whisper_ratio"] = round(actual_time / duration, 2)


async def _translate(job_id: str, input_srt: Path, output_srt: Path, language: str = None) -> None:
    entries = parse_srt(input_srt)
    total = len(entries)
    translated_entries = []

    for i in range(0, total, BATCH_SIZE):
        batch = entries[i:i + BATCH_SIZE]
        texts = [e.text for e in batch]

        try:
            translations = await asyncio.to_thread(translate_batch, texts, language)
        except Exception:
            translations = []
            for t in texts:
                try:
                    tr = await asyncio.to_thread(translate_single, t, language)
                except Exception:
                    tr = "[翻译失败]"
                translations.append(tr)

        for j, entry in enumerate(batch):
            translated_entries.append(SrtEntry(
                index=entry.index,
                start=entry.start,
                end=entry.end,
                text=translations[j],
            ))

        step_progress = min(100, int((i + len(batch)) / total * 100))
        _update(job_id, step=3, step_progress=step_progress)

    write_srt(translated_entries, output_srt)


async def _burn_subtitles(input_video: Path, srt_path: Path, output_video: Path) -> None:
    srt_escaped = str(srt_path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    cmd = [
        "ffmpeg", "-i", str(input_video),
        "-vf", f"subtitles='{srt_escaped}':force_style='FontSize=22,FontName=PingFang SC'",
        "-c:a", "copy",
        str(output_video), "-y"
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    code = await proc.wait()
    if code != 0:
        raise RuntimeError("FFmpeg 字幕合成失败")
