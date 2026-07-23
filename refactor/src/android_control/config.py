"""Typed runtime configuration for the refactored control plane."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    public_url: str = "https://m.buonme.com"
    data_dir: Path = Path("./runtime")
    database_path: Path = Path("./runtime/control.db")
    adb_path: str = "adb"
    command_timeout_seconds: float = 15.0
    allow_demo_device: bool = False
    admin_username: str = "admin"
    admin_password_file: Path = Path("./runtime/admin-password")
    session_secret_file: Path = Path("./runtime/session-secret")
    session_max_age_seconds: int = 43_200
    cookie_secure: bool = True

    model_config = SettingsConfigDict(
        env_prefix="CONTROL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def prepare(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "media").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "artifacts").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def read_secret(path: Path, label: str) -> str:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except FileNotFoundError as exc:
            raise RuntimeError(f"{label} file is missing: {path}") from exc
        if len(value) < 16:
            raise RuntimeError(f"{label} must contain at least 16 characters")
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare()
    return settings
