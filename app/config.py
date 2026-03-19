from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"

WHISPER_MODEL = "large-v3"
OLLAMA_MODEL = "qwen2.5:14b"
OLLAMA_BASE_URL = "http://localhost:11434"

MAX_UPLOAD_SIZE = 10 * 1024 * 1024 * 1024  # 10GB
