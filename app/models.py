"""Data models for Device, Task, TaskLog, Video, and VideoAssignment."""

import json

from sqlmodel import SQLModel, Field
from sqlalchemy import UniqueConstraint
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List


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
    template_vars_json: Optional[str] = None  # JSON-serialized template variables
    use_reasoning: bool = True
    execution_mode: str = "auto"  # "auto" | "script" | "ai"
    max_steps: int = 20
    status: TaskStatus = TaskStatus.PENDING
    result: Optional[str] = None  # AI completion reason/summary
    steps_taken: int = 0
    error: Optional[str] = None
    retry_count: int = 0  # Current retry attempt
    max_retries: int = 2  # Max retry attempts for transient errors
    assignment_id: Optional[int] = None  # Link back to VideoAssignment
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    @property
    def template_vars(self) -> Optional[dict]:
        """Deserialize template_vars from JSON."""
        if self.template_vars_json:
            try:
                return json.loads(self.template_vars_json)
            except (json.JSONDecodeError, TypeError):
                return None
        return None

    @template_vars.setter
    def template_vars(self, value: Optional[dict]) -> None:
        """Serialize template_vars to JSON."""
        if value is not None:
            self.template_vars_json = json.dumps(value, ensure_ascii=False)
        else:
            self.template_vars_json = None


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
    user_id: int = Field(default=1, foreign_key="user.id")
    token: str = Field(index=True, unique=True)  # secrets.token_urlsafe(32)
    name: str = ""  # Human-readable label
    is_active: bool = True
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class User(SQLModel, table=True):
    """Simple user model for device registration authentication."""

    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(index=True, unique=True)
    password: str  # Plain text for internal tool
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DeviceLinkStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class DeviceLinkRequest(SQLModel, table=True):
    """Pending device approval requests."""

    id: Optional[int] = Field(default=None, primary_key=True)
    request_id: str = Field(index=True, unique=True)
    username: str = Field(index=True)
    user_id: Optional[int] = Field(default=None, index=True)
    device_name: str
    device_model: Optional[str] = None
    android_version: Optional[str] = None
    sdk_int: Optional[int] = None
    manufacturer: Optional[str] = None
    helper_version_name: Optional[str] = None
    helper_version_code: Optional[int] = None
    helper_build_sha: Optional[str] = None
    status: DeviceLinkStatus = DeviceLinkStatus.PENDING
    claimed_device_id: Optional[int] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime = Field(index=True)
    reviewed_at: Optional[datetime] = None
    reviewed_by_user_id: Optional[int] = None
    reject_reason: Optional[str] = None
    client_fingerprint: Optional[str] = None


# --- Pydantic schemas for API request/response ---


class HelperInfo(SQLModel):
    version_name: Optional[str] = None
    version_code: Optional[int] = None
    build_sha: Optional[str] = None


class DeviceLinkRequestCreate(SQLModel):
    username: str
    device_name: str
    device_model: Optional[str] = None
    android_version: Optional[str] = None
    sdk_int: Optional[int] = None
    manufacturer: Optional[str] = None
    helper: Optional[HelperInfo] = None


class DeviceLinkRequestRead(SQLModel):
    request_id: str
    username: str
    device_name: str
    device_model: Optional[str]
    android_version: Optional[str]
    status: DeviceLinkStatus
    created_at: datetime
    expires_at: datetime


class DeviceLinkStatusRead(SQLModel):
    status: DeviceLinkStatus
    device_id: Optional[int] = None
    device_name: Optional[str] = None
    device_token: Optional[str] = None
    ws_url: Optional[str] = None
    message: Optional[str] = None


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



# =============================================================================
# Video Management Models
# =============================================================================


class VideoStatus(str, Enum):
    AVAILABLE = "available"
    ARCHIVED = "archived"


class PushStatus(str, Enum):
    PENDING = "pending"
    PUSHED = "pushed"
    PUSH_FAILED = "push_failed"
    # Legacy compat: old rows may still have these values
    UPLOADED = "uploaded"
    FAILED = "failed"


class UploadStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    UPLOADED = "uploaded"
    UPLOAD_FAILED = "upload_failed"
    VERIFY_FAILED = "verify_failed"


class MetricsStatus(str, Enum):
    PENDING = "pending"
    SYNCING = "syncing"
    SYNCED = "synced"
    NEEDS_REVIEW = "needs_review"
    SYNC_FAILED = "sync_failed"
    DISABLED = "disabled"


class Video(SQLModel, table=True):
    """Represents a video file stored on the server."""

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str  # Original filename
    filepath: str  # /data/videos/xxx.mp4
    file_hash: str = Field(index=True)  # SHA-256 — deduplication
    file_size: int  # Bytes
    duration: Optional[float] = None  # Seconds
    title: Optional[str] = None  # User-defined title
    tags: Optional[str] = None  # Comma-separated tags
    description: Optional[str] = None  # User-defined description
    status: VideoStatus = VideoStatus.AVAILABLE
    file_cleaned_at: Optional[datetime] = None  # When physical file was deleted (auto-cleanup)
    # AI-generated metadata suggestions (latest / active)
    ai_title: Optional[str] = None
    ai_tags: Optional[str] = None
    ai_description: Optional[str] = None
    ai_generated_at: Optional[datetime] = None
    thumbnail: Optional[str] = None  # Path to AI-selected thumbnail
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class VideoAIMetadata(SQLModel, table=True):
    """Cached AI-generated metadata per video × language × platform.

    Avoids re-generating (and re-spending tokens) for the same combo.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(index=True)
    language: str  # vi, en, ja, ko, zh, th, id, auto
    platform: str  # tiktok, youtube, instagram, facebook
    ai_title: str
    ai_tags: str  # Comma-separated
    ai_description: str
    thumbnail: Optional[str] = None
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class VideoAssignment(SQLModel, table=True):
    """Assignment of a video to a specific device/platform.

    Constraint: UNIQUE(video_id, device_id, platform) — 1 target per device/platform.
    """

    __table_args__ = (
        UniqueConstraint(
            "video_id",
            "device_id",
            "platform",
            name="uq_videoassignment_video_device_platform",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    video_id: int = Field(foreign_key="video.id")
    device_id: int = Field(foreign_key="device.id")
    platform: str  # tiktok / youtube / instagram / facebook
    push_status: PushStatus = PushStatus.PENDING
    upload_status: UploadStatus = UploadStatus.PENDING
    device_path: Optional[str] = None  # /sdcard/DCIM/xxx.mp4 — used to bind the exact file
    pushed_at: Optional[datetime] = None
    uploaded_at: Optional[datetime] = None
    task_id: Optional[int] = None  # Link to upload Task
    error: Optional[str] = None  # Legacy field
    last_error: Optional[str] = None  # Latest error from upload attempt
    last_run_at: Optional[datetime] = None  # When last upload was attempted
    # --- Metrics tracking (Phase A) ---
    metrics_status: MetricsStatus = MetricsStatus.PENDING
    metrics_last_synced_at: Optional[datetime] = None
    metrics_error: Optional[str] = None
    post_locator: Optional[str] = None  # JSON: {caption_fingerprint, upload_timestamp, grid_position_hint, account_name}
    latest_views: Optional[int] = None
    latest_likes: Optional[int] = None
    latest_comments: Optional[int] = None
    latest_shares: Optional[int] = None
    metrics_task_id: Optional[int] = None  # Link to metrics sync Task (separate from upload task_id)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class VideoAssignmentMetricSnapshot(SQLModel, table=True):
    """Historical record of a single metrics sync for an assignment.

    Each row = one sync attempt (successful or partial).
    Latest state lives on VideoAssignment; this table provides trend/history.
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: int = Field(foreign_key="videoassignment.id", index=True)
    views: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    source: str = "post_detail"  # grid | post_detail | manual
    raw_payload: Optional[str] = None  # JSON dump of all data read
    artifact_dir: Optional[str] = None  # Path to debug artifacts
    error: Optional[str] = None  # Error message if sync was partial/failed
    collected_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class DeviceAccount(SQLModel, table=True):
    """Maps a device to a social media account.

    Each device can have 1 account on each platform.
    Constraint: UNIQUE(device_id, platform) — 1 account per device per platform.
    """

    __table_args__ = (
        UniqueConstraint("device_id", "platform", name="uq_deviceaccount_device_platform"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: int = Field(foreign_key="device.id")
    platform: str  # tiktok / youtube / instagram / facebook
    account_name: Optional[str] = None  # @username
    notes: Optional[str] = None
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


# --- Pydantic schemas for Video API ---


class VideoRead(SQLModel):
    """Schema for video responses."""

    id: int
    filename: str
    filepath: str
    file_hash: str
    file_size: int
    duration: Optional[float]
    title: Optional[str]
    tags: Optional[str]
    description: Optional[str]
    status: VideoStatus
    ai_title: Optional[str]
    ai_tags: Optional[str]
    ai_description: Optional[str]
    ai_generated_at: Optional[datetime]
    created_at: datetime


class VideoAssignmentRead(SQLModel):
    """Schema for assignment responses."""

    id: int
    video_id: int
    device_id: int
    platform: str
    push_status: PushStatus
    upload_status: UploadStatus
    device_path: Optional[str]
    pushed_at: Optional[datetime]
    uploaded_at: Optional[datetime]
    task_id: Optional[int]
    error: Optional[str]
    last_error: Optional[str]
    last_run_at: Optional[datetime]
    created_at: datetime


class VideoDetail(SQLModel):
    """Video with its assignments."""

    id: int
    filename: str
    filepath: str
    file_hash: str
    file_size: int
    duration: Optional[float]
    title: Optional[str]
    tags: Optional[str]
    description: Optional[str]
    status: VideoStatus
    ai_title: Optional[str]
    ai_tags: Optional[str]
    ai_description: Optional[str]
    ai_generated_at: Optional[datetime]
    created_at: datetime
    assignments: List[VideoAssignmentRead] = []


class AssignCreate(SQLModel):
    """Schema for assigning a video to a device."""

    device_id: int
    platform: str


class AssignmentUpdate(SQLModel):
    """Schema for moving an assignment to another device/platform."""

    device_id: Optional[int] = None
    platform: Optional[str] = None


class AutoAssignCreate(SQLModel):
    """Schema for auto-assign request."""

    video_ids: Optional[List[int]] = None  # None = all available videos
    platform: str


class DeviceAccountCreate(SQLModel):
    """Schema for creating/updating a device-account mapping."""

    device_id: int
    platform: str
    account_name: Optional[str] = None
    notes: Optional[str] = None


class DeviceAccountRead(SQLModel):
    """Schema for device-account responses."""

    id: int
    device_id: int
    platform: str
    account_name: Optional[str]
    notes: Optional[str]
    created_at: datetime


# =============================================================================
# Upload Pipeline Orchestration Schemas
# =============================================================================


class RunUploadRequest(SQLModel):
    """Schema for run-upload endpoint."""

    auto_push: bool = True  # Auto-push via ADB if not yet pushed
    force: bool = False  # Bypass rerun cooldown for explicit manual retry


class RunBatchUploadRequest(SQLModel):
    """Schema for batch run-upload endpoint."""

    assignment_ids: List[int]
    auto_push: bool = True
    force: bool = False


class MetricsManualInput(SQLModel):
    """Schema for manual metrics input endpoint."""

    views: Optional[int] = Field(default=None, ge=0)
    likes: Optional[int] = Field(default=None, ge=0)
    comments: Optional[int] = Field(default=None, ge=0)
    shares: Optional[int] = Field(default=None, ge=0)
