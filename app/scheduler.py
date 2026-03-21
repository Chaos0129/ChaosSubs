"""Task scheduler — pipeline concurrency with per-step resource locks."""
import asyncio
from enum import Enum


class StepStatus(str, Enum):
    PENDING = "pending"    # 待执行
    QUEUING = "queuing"    # 排队中（资源被占）
    RUNNING = "running"    # 运行中
    DONE = "done"          # 已完成
    ERROR = "error"        # 失败


# Resource locks
# Step 1 (FFmpeg): no lock, concurrent
# Step 2 (Whisper): exclusive
# Step 3 (VAD): no lock, concurrent
# Step 4 (Ollama translate): exclusive
# Step 5 (Ollama polish): shares lock with step 4

# Global task limit — controls how many tasks can run pipeline simultaneously
# On 16GB machine, only 1 task at a time to avoid OOM
GLOBAL_TASK_LOCK = asyncio.Semaphore(1)

_concurrent_lock = asyncio.Semaphore(4)  # step 1 & 3, max 4 concurrent
_whisper_lock = asyncio.Semaphore(1)     # step 2, exclusive
_ollama_lock = asyncio.Semaphore(1)      # step 4 & 5, exclusive

STEP_LOCKS = {
    1: _concurrent_lock,
    2: _whisper_lock,
    3: _concurrent_lock,
    4: _ollama_lock,
    5: _ollama_lock,
}

STEP_NAMES = {
    1: "提取音频",
    2: "语音识别",
    3: "时间轴校正",
    4: "翻译字幕",
    5: "润色优化",
}


def get_step_lock(step: int):
    return STEP_LOCKS.get(step)


def get_step_name(step: int) -> str:
    return STEP_NAMES.get(step, f"步骤{step}")
