import asyncio
import json
import subprocess
import time
from pathlib import Path

from app.config import UPLOAD_DIR, WHISPER_MODEL
from app.srt_utils import whisper_segments_to_srt, write_srt, parse_srt, SrtEntry
from app.translate import translate_batch, translate_single, polish_batch
from app.job_manager import jobs, save_job
from app.scheduler import StepStatus, get_step_lock, get_step_name, GLOBAL_TASK_LOCK

BATCH_SIZE = 10
TOTAL_STEPS = 5
STEP_WEIGHTS = {1: 2, 2: 30, 3: 2, 4: 35, 5: 31}
WHISPER_SPEED_RATIO = 1.5


def _init_steps(job_id: str):
    """Initialize per-step status tracking."""
    jobs[job_id]["steps"] = {
        i: {"status": StepStatus.PENDING, "name": get_step_name(i)}
        for i in range(1, TOTAL_STEPS + 1)
    }


def _set_step(job_id: str, step: int, status: StepStatus, **extra):
    """Update a step's status and recalculate overall progress."""
    if job_id not in jobs:
        return
    now = time.time()
    step_data = jobs[job_id]["steps"][step]
    step_data["status"] = status
    if status == StepStatus.RUNNING and "started_at" not in step_data:
        step_data["started_at"] = now
    if status == StepStatus.DONE and "started_at" in step_data:
        step_data["finished_at"] = now
        step_data["duration"] = round(now - step_data["started_at"], 1)
    jobs[job_id]["current_step"] = step
    jobs[job_id]["step_name"] = f"{get_step_name(step)} — {_status_label(status)}"

    # Recalculate overall progress
    overall = 0
    for s in range(1, TOTAL_STEPS + 1):
        st = jobs[job_id]["steps"][s]["status"]
        if st == StepStatus.DONE:
            overall += STEP_WEIGHTS.get(s, 0)
        elif st == StepStatus.RUNNING:
            overall += STEP_WEIGHTS.get(s, 0) * extra.get("step_progress", 0) / 100

    jobs[job_id]["overall_progress"] = min(100, int(overall))

    # ETA
    start_time = jobs[job_id].get("start_time")
    if start_time and overall > 2:
        elapsed = time.time() - start_time
        remaining = max(0, elapsed / (overall / 100) - elapsed)
        jobs[job_id]["eta_seconds"] = int(remaining)
    else:
        jobs[job_id]["eta_seconds"] = -1

    for k, v in extra.items():
        jobs[job_id][k] = v


def _status_label(status: StepStatus) -> str:
    return {
        StepStatus.PENDING: "待执行",
        StepStatus.QUEUING: "排队中",
        StepStatus.RUNNING: "运行中",
        StepStatus.DONE: "已完成",
        StepStatus.ERROR: "失败",
    }.get(status, str(status))


async def _acquire_step(job_id: str, step: int):
    """Acquire the resource lock for a step. Updates status to queuing/running."""
    lock = get_step_lock(step)
    if lock is None:
        # No lock needed, run immediately
        _set_step(job_id, step, StepStatus.RUNNING)
        save_job(job_id)
        return

    # Show queuing status while waiting for lock
    _set_step(job_id, step, StepStatus.QUEUING)
    save_job(job_id)

    await lock.acquire()

    _set_step(job_id, step, StepStatus.RUNNING)
    save_job(job_id)


def _release_step(step: int):
    """Release the resource lock for a step."""
    lock = get_step_lock(step)
    if lock is not None:
        lock.release()


async def run_pipeline(job_id: str, resume_from: int = 1) -> None:
    """Generate subtitles with per-step locking for concurrency."""
    job_dir = UPLOAD_DIR / job_id
    input_video = _find_input_video(job_dir / "input")
    audio_path = job_dir / "process" / "audio.wav"
    original_srt = job_dir / "output" / "original.srt"
    translated_srt = job_dir / "output" / "translated_zh.srt"

    _init_steps(job_id)

    # Mark completed steps for resumed jobs
    for s in range(1, resume_from):
        _set_step(job_id, s, StepStatus.DONE)

    # Wait for global slot
    jobs[job_id]["step_name"] = "排队等待中..."
    jobs[job_id]["status"] = "queuing"
    save_job(job_id)

    await GLOBAL_TASK_LOCK.acquire()
    jobs[job_id]["status"] = "processing"
    jobs[job_id]["start_time"] = time.time()
    save_job(job_id)

    try:
        # Step 1: Extract audio
        if resume_from <= 1:
            await _acquire_step(job_id, 1)
            try:
                await _extract_audio(input_video, audio_path)
                _set_step(job_id, 1, StepStatus.DONE, current_stage="extract_audio")
            finally:
                _release_step(1)

        # Get duration
        duration = await _get_duration(input_video)
        jobs[job_id]["video_duration"] = duration

        # Step 2: Whisper transcription
        if resume_from <= 2:
            await _acquire_step(job_id, 2)
            try:
                language = jobs[job_id].get("language")
                await _transcribe_with_progress(job_id, audio_path, original_srt, language, duration)
                _set_step(job_id, 2, StepStatus.DONE, current_stage="transcribe")
            finally:
                _release_step(2)

        # Step 3: VAD time correction
        if resume_from <= 3:
            await _acquire_step(job_id, 3)
            try:
                await _correct_srt_timing(audio_path, original_srt)
                _set_step(job_id, 3, StepStatus.DONE, current_stage="correct_timing")
            finally:
                _release_step(3)

        # Step 4: Translate
        if resume_from <= 4:
            await _acquire_step(job_id, 4)
            try:
                language = jobs[job_id].get("language")
                await _translate(job_id, original_srt, translated_srt, language)
                _set_step(job_id, 4, StepStatus.DONE, current_stage="translate")
            finally:
                _release_step(4)

        # Step 5: Polish
        if resume_from <= 5:
            await _acquire_step(job_id, 5)
            try:
                await _polish(job_id, translated_srt)
                _set_step(job_id, 5, StepStatus.DONE, current_stage="polish")
            finally:
                _release_step(5)

        jobs[job_id]["status"] = "done"
        jobs[job_id]["step_name"] = "字幕生成完成"
        jobs[job_id]["overall_progress"] = 100
        jobs[job_id]["completed_at"] = time.time()
        save_job(job_id)

        # Unload Ollama model to free memory
        await _unload_ollama()

    except Exception as e:
        current = jobs[job_id].get("current_step", 1)
        _set_step(job_id, current, StepStatus.ERROR)
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = str(e)
        _release_step(current)
        save_job(job_id)
    finally:
        GLOBAL_TASK_LOCK.release()


# ===== Step implementations =====

def _find_input_video(input_dir: Path) -> Path:
    if not input_dir.exists():
        raise RuntimeError("找不到输入目录")
    for f in input_dir.iterdir():
        if f.suffix.lower() in (".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".ts", ".m4v"):
            return f
    raise RuntimeError("找不到输入视频文件")


async def _get_duration(video_path: Path) -> float:
    cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(video_path)]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    stdout, _ = await proc.communicate()
    try:
        return float(json.loads(stdout)["format"]["duration"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return 0.0


async def _extract_audio(input_video: Path, output_audio: Path) -> None:
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-i", str(input_video), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", str(output_audio), "-y"]
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if await proc.wait() != 0:
        raise RuntimeError("FFmpeg 音频提取失败")


async def _transcribe_with_progress(job_id, audio_path, output_srt, language, duration):
    done_event = asyncio.Event()
    estimated = max(duration * WHISPER_SPEED_RATIO, 30)
    start = time.time()

    async def _progress():
        while not done_event.is_set():
            elapsed = time.time() - start
            raw = elapsed / estimated
            pct = min(raw * 100 if raw < 0.8 else 80 + (raw - 0.8) * 75, 95)
            _set_step(job_id, 2, StepStatus.RUNNING, step_progress=int(pct))
            await asyncio.sleep(1)

    task = asyncio.create_task(_progress())

    def _run():
        import mlx_whisper
        result = mlx_whisper.transcribe(
            str(audio_path),
            path_or_hf_repo=f"mlx-community/whisper-{WHISPER_MODEL}-mlx",
            language=language, word_timestamps=True,
        )
        output_srt.parent.mkdir(parents=True, exist_ok=True)
        entries = whisper_segments_to_srt([{"start": s["start"], "end": s["end"], "text": s["text"]} for s in result["segments"]])
        write_srt(entries, output_srt)

    try:
        await asyncio.to_thread(_run)
    finally:
        done_event.set()
        task.cancel()


async def _unload_ollama():
    """Unload Ollama model to free memory after translation/polish."""
    try:
        import urllib.request
        from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL
        data = json.dumps({"model": OLLAMA_MODEL, "keep_alive": 0}).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_BASE_URL}/api/generate", data=data,
            headers={"Content-Type": "application/json"},
        )
        await asyncio.to_thread(lambda: urllib.request.urlopen(req, timeout=5))
    except Exception:
        pass


async def _correct_srt_timing(audio_path, srt_path):
    from app.audio_utils import detect_speech_segments
    from app.srt_utils import seconds_to_srt_time, srt_time_to_seconds

    speech_segments = await asyncio.to_thread(detect_speech_segments, audio_path)
    entries = parse_srt(srt_path)
    if not speech_segments or not entries:
        return

    corrected = []
    for entry in entries:
        srt_start = srt_time_to_seconds(entry.start)
        srt_end = srt_time_to_seconds(entry.end)
        dur = srt_end - srt_start

        new_start = srt_start
        for seg_start, seg_end in speech_segments:
            if seg_end > srt_start - 0.5:
                if seg_start > srt_start + 0.3:
                    new_start = seg_start
                break

        corrected.append(SrtEntry(
            index=entry.index,
            start=seconds_to_srt_time(new_start),
            end=seconds_to_srt_time(new_start + dur),
            text=entry.text,
        ))
    write_srt(corrected, srt_path)


async def _translate(job_id, input_srt, output_srt, language):
    entries = parse_srt(input_srt)
    total = len(entries)
    translated = []

    for i in range(0, total, BATCH_SIZE):
        batch = entries[i:i + BATCH_SIZE]
        texts = [e.text for e in batch]
        try:
            results = await asyncio.to_thread(translate_batch, texts, language)
        except Exception:
            results = []
            for t in texts:
                try:
                    results.append(await asyncio.to_thread(translate_single, t, language))
                except Exception:
                    results.append("[翻译失败]")

        for j, entry in enumerate(batch):
            translated.append(SrtEntry(index=entry.index, start=entry.start, end=entry.end, text=results[j]))

        pct = min(100, int((i + len(batch)) / total * 100))
        _set_step(job_id, 4, StepStatus.RUNNING, step_progress=pct)

    output_srt.parent.mkdir(parents=True, exist_ok=True)
    write_srt(translated, output_srt)


async def _polish(job_id, srt_path):
    entries = parse_srt(srt_path)
    total = len(entries)
    polished_entries = []
    polished_count = 0
    kept_count = 0
    all_texts = [e.text.replace("\n", " ") for e in entries]

    for i in range(0, total, BATCH_SIZE):
        batch = entries[i:i + BATCH_SIZE]
        texts = all_texts[i:i + BATCH_SIZE]
        ctx_before = all_texts[max(0, i - 3):i]
        ctx_after = all_texts[i + BATCH_SIZE:i + BATCH_SIZE + 3]

        try:
            results = await asyncio.to_thread(polish_batch, texts, ctx_before, ctx_after)
        except Exception:
            results = [(t, False, "润色失败") for t in texts]

        for j, entry in enumerate(batch):
            text, was_polished, reason = results[j]
            if was_polished:
                polished_count += 1
            else:
                kept_count += 1
            polished_entries.append(SrtEntry(index=entry.index, start=entry.start, end=entry.end, text=text))

        pct = min(100, int((i + len(batch)) / total * 100))
        _set_step(job_id, 5, StepStatus.RUNNING, step_progress=pct,
                  step_name=f"润色优化 — 运行中 ({polished_count}条润色, {kept_count}条保留)")

    write_srt(polished_entries, srt_path)
    jobs[job_id]["polish_stats"] = {"polished": polished_count, "kept": kept_count}
