import asyncio
import shutil
import uuid

from fastapi import FastAPI, Form, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import UPLOAD_DIR, MAX_UPLOAD_SIZE
from app.tasks import run_pipeline, run_burn, jobs

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


@app.post("/upload")
async def upload_video(file: UploadFile = File(...), language: str = Form("ja")):
    job_id = str(uuid.uuid4())[:8]
    job_dir = UPLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    ext = file.filename.rsplit(".", 1)[-1] if "." in file.filename else "mp4"
    input_path = job_dir / f"input.{ext}"

    size = 0
    with open(input_path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                shutil.rmtree(job_dir)
                return JSONResponse(
                    {"error": f"文件过大，最大支持 {MAX_UPLOAD_SIZE // (1024**3)}GB"},
                    status_code=413,
                )
            f.write(chunk)

    jobs[job_id] = {
        "status": "processing",
        "step": 0,
        "step_name": "视频导入成功，准备处理...",
        "step_progress": 0,
        "overall_progress": 0,
        "eta_seconds": -1,
        "error": None,
        "file_name": file.filename,
        "file_size": size,
        "language": language if language != "auto" else None,
    }

    asyncio.create_task(run_pipeline(job_id))

    return {"job_id": job_id}


@app.get("/job/{job_id}")
async def get_job_status(job_id: str):
    """Query job status — used by frontend to restore after refresh."""
    if job_id not in jobs:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    job = jobs[job_id]
    safe_job = {k: v for k, v in job.items() if k != "start_time"}
    return safe_job


@app.post("/burn/{job_id}")
async def burn_subtitles(job_id: str):
    """Phase 2: User confirms subtitles are OK, burn into video."""
    if job_id not in jobs:
        return JSONResponse({"error": "任务不存在"}, status_code=404)
    if jobs[job_id].get("status") != "done":
        return JSONResponse({"error": "字幕尚未生成完成"}, status_code=400)

    srt_path = UPLOAD_DIR / job_id / "translated_zh.srt"
    if not srt_path.exists():
        return JSONResponse({"error": "字幕文件不存在"}, status_code=404)

    asyncio.create_task(run_burn(job_id))
    return {"status": "burning"}


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
            safe_job = {k: v for k, v in job.items() if k != "start_time"}
            await websocket.send_json(safe_job)
            status = job.get("status")
            burn = job.get("burn_status")
            if status == "error":
                break
            if burn in ("done", "error"):
                break
            if status == "done" and burn is None:
                break
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        await websocket.close()


@app.delete("/job/{job_id}")
async def cleanup_job(job_id: str):
    """Delete job data (uploaded video, audio, subtitles, output)."""
    job_dir = UPLOAD_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    if job_id in jobs:
        del jobs[job_id]
    return {"status": "cleaned"}


@app.get("/download/{job_id}/original-srt")
async def download_original_srt(job_id: str):
    srt_path = UPLOAD_DIR / job_id / "original.srt"
    if not srt_path.exists():
        return JSONResponse({"error": "原始字幕文件不存在"}, status_code=404)
    return FileResponse(
        srt_path,
        media_type="application/x-subrip",
        filename=f"original_{job_id}.srt",
    )


@app.get("/download/{job_id}/srt")
async def download_srt(job_id: str):
    srt_path = UPLOAD_DIR / job_id / "translated_zh.srt"
    if not srt_path.exists():
        return JSONResponse({"error": "字幕文件不存在"}, status_code=404)
    return FileResponse(
        srt_path,
        media_type="application/x-subrip",
        filename=f"subtitles_zh_{job_id}.srt",
    )


@app.get("/download/{job_id}/video")
async def download_video(job_id: str):
    video_path = UPLOAD_DIR / job_id / "output.mp4"
    if not video_path.exists():
        return JSONResponse({"error": "视频文件不存在"}, status_code=404)
    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"chaossubs_{job_id}.mp4",
    )
