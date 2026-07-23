"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pathlib import Path

# Project root directory (source code location)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Runtime data directory (must be writable)
# Override with RUNTIME_DATA_DIR env var for production
import os
RUNTIME_DIR = Path(os.environ.get("RUNTIME_DATA_DIR", "/tmp/android-control"))
DATA_DIR = RUNTIME_DIR / "data"
SCREENSHOTS_DIR = RUNTIME_DIR / "screenshots"


class Settings(BaseSettings):
    """App settings loaded from .env file."""

    # LLM Configuration — Primary: GPT-4o, Fallback: DeepSeek
    openai_api_key: str = ""       # GPT-4o API key (primary)
    deepseek_api_key: str = ""     # DeepSeek API key (fallback)
    llm_base_url: str = ""         # Empty = OpenAI default, or custom endpoint
    llm_model: str = "gpt-4o"      # Primary model

    # ADB
    adb_path: str = "adb"

    # Accessibility Service Backend
    accessibility_ws_port: int = 38301     # WebSocket port on helper APK
    default_backend: str = "auto"          # "auto" | "adb" | "accessibility"

    # Database
    database_url: str = f"sqlite:///{DATA_DIR}/android_control.db"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # LiveKit Android screen streaming
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    livekit_token_ttl_seconds: int = 600

    # Auth / Session
    secret_key: str = "CHANGE-THIS-IN-PRODUCTION-USE-RANDOM-32-CHARS"
    session_expire_hours: int = 24  # Session cookie lifetime

    # DroidRun
    droidrun_config_path: str = str(PROJECT_ROOT / "config.yaml")

    # Paths
    screenshots_dir: str = str(SCREENSHOTS_DIR)

    # Video Management
    video_storage_dir: str = str(DATA_DIR / "videos")  # Server-side video cache
    device_video_path: str = "/sdcard/DCIM/AndroidControl"  # Path on device

    # AI Metadata (video analysis)
    ai_metadata_model: str = "gpt-4o-mini"  # Vision model for frame analysis
    ai_metadata_max_frames: int = 5  # Number of keyframes to extract

    model_config = {
        "env_file": str(RUNTIME_DIR / ".env"),
        "env_file_encoding": "utf-8",
        "env_ignore_empty": True,
    }


# Singleton
settings = Settings()

# Ensure directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
Path(settings.video_storage_dir).mkdir(parents=True, exist_ok=True)
