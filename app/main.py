import asyncio
import shutil
import uuid

from fastapi import FastAPI, Form, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
from app.tasks import run_pipeline
from app.job_manager import (
    jobs, create_job, save_job, scan_all_jobs,
    restore_job, detect_job_status,
)

app = FastAPI(title="ChaosSubs")

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def index():
    return FileResponse("static/index.html")


# ===== Task Management API =====

@app.get("/jobs")
async def list_jobs():
    """List all jobs with status, including live progress for running jobs."""
    result = scan_all_jobs()
    # Merge live data ONLY for jobs actually running in memory
    for job in result:
        jid = job["job_id"]
        if jid in jobs and jobs[jid].get("status") == "processing":
            live = jobs[jid]
            job["status"] = "processing"
            job["step"] = live.get("current_step", 0)
            job["step_name"] = live.get("step_name", "")
            job["overall_progress"] = live.get("overall_progress", 0)
            job["eta_seconds"] = live.get("eta_seconds", -1)
            if "steps" in live:
                job["steps"] = {str(k): v for k, v in live["steps"].items()}
        # Don't touch jobs not in memory — scan_all_jobs already set correct status
    return result


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), language: str = Form("ja")):
    job_id = str(uuid.uuid4())[:8]
    job_dir = UPLOAD_DIR / job_id / "input"
    job_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "mp4"
    input_path = job_dir / f"{file.filename}"

    size = 0
    with open(input_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                shutil.rmtree(UPLOAD_DIR / job_id)
                return JSONResponse(
                    {"error": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // (1024**3)}GB"},
                    status_code=413,
                )
            f.write(chunk)

    lang = language if language != "auto" else None
    create_job(job_id, file.filename, size, lang)
    asyncio.create_task(run_pipeline(job_id))

    return {"job_id": job_id}


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Query job status."""
    if job_id in jobs:
        job = jobs[job_id]
        safe_job = {k: v for k, v in job.items() if k not in ("start_time",)}
        return safe_job

    # Try loading from disk
    status = detect_job_status(job_id)
    if status == "missing":
        return JSONResponse({"error": "任务不存在"}, status_code=404)

    from app.job_manager import load_job
    job_data = load_job(job_id) or {}
    job_data["status"] = status
    return job_data


@app.post("/job/{job_id}/resume")
async def resume_job(job_id: str):
    """Resume a paused job."""
    status = detect_job_status(job_id)
    if status not in ("paused", "failed"):
        return JSONResponse({"error": f"任务状态为 {status}，无法恢复"}, status_code=400)

    job_data = restore_job(job_id)
    if not job_data:
        return JSONResponse({"error": "无法恢复任务"}, status_code=500)

    # Determine resume step
    from app.job_manager import infer_stage
    stage = infer_stage(job_id)
    stage_to_step = {
        "upload": 1,
        "extract_audio": 2,
        "transcribe": 3,
        "correct_timing": 4,
        "translate": 5,
        "polish": 5,
    }
    resume_from = stage_to_step.get(stage, 1)

    asyncio.create_task(run_pipeline(job_id, resume_from=resume_from))
    return {"status": "resumed", "resume_from_step": resume_from}


@app.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete job and all its data."""
    job_dir = UPLOAD_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    if job_id in jobs:
        del jobs[job_id]
    return {"status": "deleted"}


@app.delete("/job/{job_id}/process")
async def clean_process_data(job_id: str):
    """Delete only process data, keep input and output."""
    process_dir = UPLOAD_DIR / job_id / "process"
    if process_dir.exists():
        shutil.rmtree(process_dir)
        process_dir.mkdir()
    return {"status": "process_data_cleaned"}


@app.websocket("/ws/{job_id}")
async def websocket_progress(websocket: WebSocket, job_id: str):
    await websocket.accept()
    if job_id not in jobs:
        await websocket.send_json({"error": "任务不存在"})
        await websocket.close()
        return

    try:
        while True:
            job = jobs.get(job_id, {})
            safe_job = {k: v for k, v in job.items() if k not in ("start_time",)}
            await websocket.send_json(safe_job)
            status = job.get("status")
            if status in ("done", "error"):
                break
            await asyncio.sleep(2)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


# ===== Download endpoints =====

@app.get("/download/{job_id}/original-srt")
async def download_original_srt(job_id: str):
    srt_path = UPLOAD_DIR / job_id / "output" / "original.srt"
    if not srt_path.exists():
        return JSONResponse({"error": "原始字幕文件不存在"}, status_code=404)
    return FileResponse(
        srt_path,
        media_type="application/x-subrip",
        filename=f"original_{job_id}.srt",
    )


@app.get("/download/{job_id}/srt")
async def download_srt(job_id: str):
    srt_path = UPLOAD_DIR / job_id / "output" / "translated_zh.srt"
    if not srt_path.exists():
        return JSONResponse({"error": "字幕文件不存在"}, status_code=404)
    return FileResponse(
        srt_path,
        media_type="application/x-subrip",
        filename=f"subtitles_zh_{job_id}.srt",
    )
