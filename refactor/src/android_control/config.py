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


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare()
    return settings
