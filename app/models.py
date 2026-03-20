"""Data models for Device, Task, and TaskLog."""

from sqlmodel import SQLModel, Field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class DeviceStatus(str, Enum):
    ONLINE = "online"
    OFFLINE = "offline"
    BUSY = "busy"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Device(SQLModel, table=True):
    """Represents a connected Android device."""

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str  # "Android 1", "Pixel 7", etc.
    ip_address: str  # "192.168.1.100"
    adb_port: int = 5555
    status: DeviceStatus = DeviceStatus.OFFLINE
    last_seen: Optional[datetime] = None
    android_version: Optional[str] = None
    device_model: Optional[str] = None
    battery_level: Optional[int] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class Task(SQLModel, table=True):
    """A task to be executed on a device."""

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    command: str  # Natural language command
    template: Optional[str] = None  # Template name if used
    use_reasoning: bool = True
    execution_mode: str = "auto"  # "auto" | "script" | "ai"
    max_steps: int = 20
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None  # AI completion reason/summary
    steps_taken: int = 0
    error: Optional[str] = None
    retry_count: int = 0  # Current retry attempt
    max_retries: int = 2  # Max retry attempts for transient errors
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class TaskLog(SQLModel, table=True):
    """Individual step log within a task execution."""

    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: int = Field(foreign_key="task.id")
    step: int
    action: str  # "click", "swipe", "type", "screenshot", etc.
    detail: Optional[str] = None
    screenshot_path: Optional[str] = None
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DeviceToken(SQLModel, table=True):
    """Token for authenticating device cloud connections (SaaS mode).

    Each token maps to a specific device and user. The Android Helper APK
    uses this token to connect to: wss://server/ws/device/{token}
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    user_id: int = 1  # TODO: proper FK when User model is added
    token: str = Field(index=True, unique=True)  # secrets.token_urlsafe(32)
    name: str = ""  # Human-readable label
    is_active: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- Pydantic schemas for API request/response ---


class DeviceCreate(SQLModel):
    """Schema for creating a new device."""

    name: str
    ip_address: str
    adb_port: int = 5555


class DeviceRead(SQLModel):
    """Schema for device responses."""

    id: int
    name: str
    ip_address: str
    adb_port: int
    status: DeviceStatus
    last_seen: Optional[datetime]
    android_version: Optional[str]
    device_model: Optional[str]
    battery_level: Optional[int]
    created_at: datetime


class TaskCreate(SQLModel):
    """Schema for creating a new task."""

    device_id: int
    command: str
    template: Optional[str] = None
    template_vars: Optional[dict] = None  # Variables for template
    use_reasoning: bool = True
    execution_mode: str = "auto"  # "auto" | "script" | "ai"
    max_steps: int = 20
    max_retries: int = 2


class BatchTaskCreate(SQLModel):
    """Schema for submitting same task to multiple devices."""

    device_ids: list[int]
    command: str
    template: Optional[str] = None
    template_vars: Optional[dict] = None
    use_reasoning: bool = True
    execution_mode: str = "auto"  # "auto" | "script" | "ai"
    max_steps: int = 20
    max_retries: int = 2


class TaskRead(SQLModel):
    """Schema for task responses."""

    id: int
    device_id: int
    command: str
    template: Optional[str]
    use_reasoning: bool
    execution_mode: str
    max_steps: int
    status: TaskStatus
    result: Optional[str]
    steps_taken: int
    error: Optional[str]
    retry_count: int
    max_retries: int
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]


class TaskLogRead(SQLModel):
    """Schema for task log responses."""

    id: int
    task_id: int
    step: int
    action: str
    detail: Optional[str]
    screenshot_path: Optional[str]
    timestamp: datetime


# --- Schedule models ---


class Schedule(SQLModel, table=True):
    """A scheduled task that runs automatically at configured times."""

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    name: str  # "Sáng lướt TikTok"
    action: str  # "tiktok_browse" | "youtube_watch" | "custom"
    execution_mode: str = "script"  # "script" | "ai"
    command: str = ""  # AI command or auto-generated
    template: Optional[str] = None
    # --- Timing ---
    start_time: str = "08:00"  # Start of time window
    end_time: str = "10:00"  # End of time window
    days_of_week: str = "daily"  # "daily" | "mon,tue,wed,thu,fri"
    repeat_count: int = 1  # Run N times within window
    random_delay_min: int = 5  # Min delay between repeats (minutes)
    random_delay_max: int = 15  # Max delay between repeats (minutes)
    # --- Script config ---
    script_count: int = 5
    script_view_time: str = "5-15"
    script_like_chance: float = 0.3
    max_steps: int = 20
    # --- Status ---
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class ScheduleCreate(SQLModel):
    """Schema for creating a schedule."""

    device_id: int
    name: str
    action: str
    execution_mode: str = "script"
    command: str = ""
    template: Optional[str] = None
    start_time: str = "08:00"
    end_time: str = "10:00"
    days_of_week: str = "daily"
    repeat_count: int = 1
    random_delay_min: int = 5
    random_delay_max: int = 15
    script_count: int = 5
    script_view_time: str = "5-15"
    script_like_chance: float = 0.3
    max_steps: int = 20


class ScheduleUpdate(SQLModel):
    """Schema for updating a schedule (all optional)."""

    name: Optional[str] = None
    action: Optional[str] = None
    execution_mode: Optional[str] = None
    command: Optional[str] = None
    template: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    days_of_week: Optional[str] = None
    repeat_count: Optional[int] = None
    random_delay_min: Optional[int] = None
    random_delay_max: Optional[int] = None
    script_count: Optional[int] = None
    script_view_time: Optional[str] = None
    script_like_chance: Optional[float] = None
    max_steps: Optional[int] = None
    enabled: Optional[bool] = None


class ScheduleRead(SQLModel):
    """Schema for schedule responses."""

    id: int
    device_id: int
    name: str
    action: str
    execution_mode: str
    command: str
    template: Optional[str]
    start_time: str
    end_time: str
    days_of_week: str
    repeat_count: int
    random_delay_min: int
    random_delay_max: int
    script_count: int
    script_view_time: str
    script_like_chance: float
    max_steps: int
    enabled: bool
    last_run: Optional[datetime]
    next_run: Optional[datetime]
    created_at: datetime

