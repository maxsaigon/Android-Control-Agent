"""Public API models and small domain types."""

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeviceStatus(StrEnum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class TransportKind(StrEnum):
    CLOUD = "cloud"
    ADB = "adb"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DeviceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    transport: TransportKind = TransportKind.CLOUD
    address: str = Field(default="", max_length=255)


class DeviceView(BaseModel):
    id: int
    name: str
    transport: TransportKind
    address: str
    status: DeviceStatus
    battery_level: int | None = None
    last_seen: str | None = None
    helper: dict[str, Any] = Field(default_factory=dict)


class ProvisionedDevice(BaseModel):
    device: DeviceView
    token: str | None = None
    websocket_url: str | None = None


class ActionRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)


class ActionResult(BaseModel):
    ok: bool = True
    action: str
    result: Any = None


class WorkflowStart(BaseModel):
    workflow: str
    params: dict[str, Any] = Field(default_factory=dict)


class RunView(BaseModel):
    id: str
    device_id: int
    workflow: str
    status: RunStatus
    params: dict[str, Any]
    steps: list[dict[str, Any]]
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None


class MediaView(BaseModel):
    id: str
    filename: str
    size_bytes: int
    sha256: str
    created_at: str
