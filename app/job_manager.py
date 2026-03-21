"""Job state management — persistence, recovery, lifecycle."""
import json
import time
from pathlib import Path
from app.config import UPLOAD_DIR

# In-memory job state
jobs: dict = {}

# Job stages in order — used to infer progress from directory contents
STAGES = [
    {"id": "upload", "name": "视频导入", "files": ["input/"]},
    {"id": "extract_audio", "name": "提取音频", "files": ["process/audio.wav"]},
    {"id": "transcribe", "name": "语音识别", "files": ["output/original.srt"]},
    {"id": "correct_timing", "name": "时间轴校正", "files": []},  # modifies original.srt in place
    {"id": "translate", "name": "翻译字幕", "files": ["output/translated_zh.srt"]},
    {"id": "polish", "name": "润色优化", "files": []},  # modifies translated_zh.srt in place
]


def _job_json_path(job_id: str) -> Path:
    return UPLOAD_DIR / job_id / "job.json"


def create_job(job_id: str, file_name: str, file_size: int, language: str = None) -> dict:
    """Create a new job and save initial state."""
    job_dir = UPLOAD_DIR / job_id
    (job_dir / "input").mkdir(parents=True, exist_ok=True)
    (job_dir / "process").mkdir(exist_ok=True)
    (job_dir / "output").mkdir(exist_ok=True)

    job = {
        "job_id": job_id,
        "status": "processing",
        "step": 0,
        "step_name": "视频导入成功，准备处理...",
        "step_progress": 0,
        "overall_progress": 0,
        "eta_seconds": -1,
        "error": None,
        "file_name": file_name,
        "file_size": file_size,
        "language": language,
        "created_at": time.time(),
        "updated_at": time.time(),
        "completed_at": None,
        "current_stage": "upload",
    }
    jobs[job_id] = job
    save_job(job_id)
    return job


def save_job(job_id: str) -> None:
    """Persist job state to job.json."""
    if job_id not in jobs:
        return
    job = jobs[job_id]
    job["updated_at"] = time.time()

    # Filter out non-serializable fields
    safe = {k: v for k, v in job.items() if k not in ("start_time",)}
    path = _job_json_path(job_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")


def load_job(job_id: str) -> dict:
    """Load job state from job.json."""
    path = _job_json_path(job_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def infer_stage(job_id: str) -> str:
    """Infer current stage from directory contents."""
    job_dir = UPLOAD_DIR / job_id
    if not job_dir.exists():
        return None

    last_stage = "upload"
    for stage in STAGES:
        if stage["files"]:
            all_exist = all((job_dir / f).exists() for f in stage["files"])
            if all_exist:
                last_stage = stage["id"]

    return last_stage


def get_job_display_name(job: dict) -> str:
    """Generate display name: filename + job_id."""
    name = job.get("file_name", "unknown")
    # Remove extension
    if "." in name:
        name = name.rsplit(".", 1)[0]
    # Truncate long names
    if len(name) > 30:
        name = name[:27] + "..."
    return f"{name} ({job.get('job_id', '?')})"


def detect_job_status(job_id: str) -> str:
    """Detect job status from job.json + directory state."""
    job_dir = UPLOAD_DIR / job_id

    if not job_dir.exists():
        return "missing"

    job_data = load_job(job_id)
    if not job_data:
        # No job.json but directory exists — corrupted
        # Check if there's at least an input file
        input_dir = job_dir / "input"
        if input_dir.exists() and any(input_dir.iterdir()):
            return "corrupted"
        return "corrupted"

    saved_status = job_data.get("status", "unknown")

    if saved_status == "done":
        output_dir = job_dir / "output"
        if (output_dir / "translated_zh.srt").exists():
            return "completed"
        return "corrupted"

    if saved_status in ("processing", "queuing"):
        # Check if it's actually running in memory right now
        if job_id in jobs:
            mem_status = jobs[job_id].get("status")
            if mem_status in ("processing", "queuing"):
                return mem_status
        return "paused"

    if saved_status == "error":
        return "failed"

    return "unknown"


def scan_all_jobs() -> list:
    """Scan uploads directory and return list of all jobs with status."""
    if not UPLOAD_DIR.exists():
        return []

    result = []
    for item in sorted(UPLOAD_DIR.iterdir()):
        if not item.is_dir():
            continue

        job_id = item.name
        status = detect_job_status(job_id)
        job_data = load_job(job_id) or {}

        result.append({
            "job_id": job_id,
            "display_name": get_job_display_name(job_data) if job_data else job_id,
            "status": status,
            "file_name": job_data.get("file_name", "unknown"),
            "created_at": job_data.get("created_at"),
            "completed_at": job_data.get("completed_at"),
            "current_stage": job_data.get("current_stage", infer_stage(job_id)),
            "language": job_data.get("language"),
        })

    # Sort by created_at descending (newest first)
    result.sort(key=lambda j: j.get("created_at") or 0, reverse=True)
    return result


def restore_job(job_id: str) -> dict:
    """Restore a paused job into memory for resuming."""
    job_data = load_job(job_id)
    if not job_data:
        return None

    # Infer actual stage from files
    actual_stage = infer_stage(job_id)
    job_data["current_stage"] = actual_stage
    job_data["status"] = "processing"

    # Figure out which step to resume from
    stage_to_step = {
        "upload": 1,
        "extract_audio": 2,
        "transcribe": 3,
        "correct_timing": 4,
        "translate": 5,
        "polish": 5,
    }
    job_data["step"] = stage_to_step.get(actual_stage, 1)

    jobs[job_id] = job_data
    save_job(job_id)
    return job_data
