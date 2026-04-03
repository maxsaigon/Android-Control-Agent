"""Video management API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session, select
from sqlalchemy import update

from app.database import get_session
from app.models import (
    Video, VideoAssignment, DeviceAccount, Device, Task, TaskStatus,
    PushStatus, UploadStatus, RunUploadRequest, RunBatchUploadRequest,
    AssignmentUpdate,
)
from app.services.video_service import video_service
from app.services.ai_metadata_service import ai_metadata_service
from app.services.task_queue import task_queue
from app.services.upload_artifacts import upload_artifacts_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/videos", tags=["videos"])
account_router = APIRouter(prefix="/api/device-accounts", tags=["device-accounts"])


# =============================================================================
# Video endpoints
# =============================================================================


@router.get("")
def list_videos(
    status: Optional[str] = None,
    platform: Optional[str] = None,
    unassigned: bool = False,
    session: Session = Depends(get_session),
):
    """List videos with optional filters.

    Query params:
    - status: available | archived
    - platform: tiktok | youtube | instagram | facebook
    - unassigned: if true + platform set, exclude already-assigned videos
    """
    return video_service.get_videos(
        session,
        status=status,
        platform=platform,
        unassigned_only=unassigned,
    )


@router.post("/upload", status_code=201)
async def upload_video(
    file: UploadFile = File(...),
    title: Optional[str] = Form(default=None),
    tags: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
):
    """Upload a video file from local machine.

    Deduplication: if the same file (SHA-256) is already uploaded, returns
    the existing record with HTTP 200 instead of 201.
    """
    if not file.filename:
        raise HTTPException(400, "No filename provided")

    # Basic MIME check
    allowed = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
    from pathlib import Path
    ext = Path(file.filename).suffix.lower()
    if ext not in allowed:
        raise HTTPException(
            400,
            f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(allowed))}",
        )

    video_dict, is_new = await video_service.upload_video(
        session, file, title=title, tags=tags
    )

    if not is_new:
        # Duplicate — return 200 with existing record + hint
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=200,
            content={**video_dict, "_duplicate": True, "created_at": str(video_dict["created_at"])},
        )

    # Serialize datetime for JSON
    video_dict["created_at"] = str(video_dict["created_at"])
    return video_dict


# NOTE: All static-path routes MUST be declared BEFORE dynamic /{video_id} routes.
# FastAPI matches routes in declaration order — static wins over dynamic only if
# declared first. Putting /assignments or /auto-assign after /{video_id} causes
# FastAPI to capture "assignments" as video_id and return 422/404.

@router.get("/assignments")
def get_assignments(
    video_id: Optional[int] = None,
    device_id: Optional[int] = None,
    platform: Optional[str] = None,
    push_status: Optional[str] = None,
    upload_status: Optional[str] = None,
    actionable_only: bool = False,
    session: Session = Depends(get_session),
):
    """Get full assignment matrix. Filter by video_id or device_id."""
    return video_service.get_assignments(
        session,
        video_id=video_id,
        device_id=device_id,
        platform=platform,
        push_status=push_status,
        upload_status=upload_status,
        actionable_only=actionable_only,
    )


@router.post("/auto-assign", status_code=201)
def auto_assign(
    body: dict,
    session: Session = Depends(get_session),
):
    """Round-robin auto-assign videos to devices that have DeviceAccount for this platform.

    Body: { "platform": "tiktok", "video_ids": [1,2,3] }  (video_ids optional)
    """
    platform = body.get("platform")
    if not platform:
        raise HTTPException(400, "platform is required")

    video_ids = body.get("video_ids")
    assignments = video_service.auto_assign(session, str(platform).lower(), video_ids)
    return {"assigned": len(assignments), "assignments": assignments}


@router.post("/assignments/{assignment_id}/push")
async def push_to_device(
    assignment_id: int,
    session: Session = Depends(get_session),
):
    """ADB push the video file to the assigned device."""
    success, message = await video_service.push_to_device(session, assignment_id)
    if not success:
        if "not found" in message.lower():
            raise HTTPException(404, message)
        raise HTTPException(500, message)
    return {"success": True, "message": message}


@router.get("/assignments/{assignment_id}/artifacts")
def get_assignment_artifacts(
    assignment_id: int,
    session: Session = Depends(get_session),
):
    """Return latest upload artifact summary for an assignment."""
    assignment = session.get(VideoAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    artifact = upload_artifacts_service.find_assignment_artifact(assignment_id)
    if not artifact:
        raise HTTPException(404, "No upload artifacts found for this assignment")
    return artifact


@router.patch("/assignments/{assignment_id}")
def update_assignment(
    assignment_id: int,
    body: AssignmentUpdate,
    session: Session = Depends(get_session),
):
    """Update assignment target device/platform."""
    if body.device_id is None and body.platform is None:
        raise HTTPException(400, "device_id or platform is required")

    assignment, error = video_service.update_assignment(
        session,
        assignment_id,
        device_id=body.device_id,
        platform=body.platform,
    )
    if error:
        if "not found" in error.lower():
            raise HTTPException(404, error)
        raise HTTPException(409, error)
    return assignment


@router.delete("/assignments/{assignment_id}", status_code=204)
def delete_assignment(
    assignment_id: int,
    session: Session = Depends(get_session),
):
    """Delete an assignment."""
    error = video_service.delete_assignment(session, assignment_id)
    if error:
        if "not found" in error.lower():
            raise HTTPException(404, error)
        raise HTTPException(409, error)


@router.post("/assignments/push-batch")
async def push_batch_to_device(
    body: dict,
    session: Session = Depends(get_session),
):
    """ADB push multiple assignments in sequence.

    Body: { "assignment_ids": [1, 2, 3] }
    """
    assignment_ids = body.get("assignment_ids") or []
    if not isinstance(assignment_ids, list) or not assignment_ids:
        raise HTTPException(400, "assignment_ids must be a non-empty list")

    results = []
    for aid in assignment_ids:
        try:
            success, message = await video_service.push_to_device(session, int(aid))
            if not success:
                results.append({
                    "assignment_id": int(aid),
                    "success": False,
                    "error": message,
                })
                continue
            results.append({
                "assignment_id": int(aid),
                "success": True,
                "message": message,
            })
        except Exception as e:
            logger.exception("Batch push failed for assignment %s", aid)
            results.append({
                "assignment_id": int(aid),
                "success": False,
                "error": str(e),
            })

    succeeded = sum(1 for r in results if r["success"])
    return {
        "total": len(assignment_ids),
        "succeeded": succeeded,
        "failed": len(assignment_ids) - succeeded,
        "results": results,
    }


# =============================================================================
# Upload Pipeline Orchestration
# =============================================================================


# Template mapping per platform
_PLATFORM_TEMPLATES = {
    "tiktok": "tiktok_upload",
    # Future: "instagram": "instagram_upload", etc.
}


@router.post("/assignments/{assignment_id}/run-upload")
async def run_upload(
    assignment_id: int,
    body: RunUploadRequest = None,
    session: Session = Depends(get_session),
):
    """One-click upload orchestration for an assignment.

    Steps:
    1. Validate assignment + device + device account
    2. Atomic idempotency: set upload_status=QUEUED atomically — reject if
       already QUEUED or RUNNING (prevents concurrent duplicate tasks)
    3. Auto-push via ADB if file not yet pushed (configurable)
    4. Create Task with platform-specific template + template_vars
       (includes device_path to bind the exact file on device)
    5. Link task to assignment
    6. Submit task to background queue
    """
    from datetime import datetime, timezone

    opts = body or RunUploadRequest()

    # --- 1. Validate assignment + device + account ---
    assignment = session.get(VideoAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")

    video = session.get(Video, assignment.video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    device = session.get(Device, assignment.device_id)
    if not device:
        raise HTTPException(404, "Device not found")

    # Check device has account for this platform
    account = session.exec(
        select(DeviceAccount).where(
            DeviceAccount.device_id == assignment.device_id,
            DeviceAccount.platform == assignment.platform,
        )
    ).first()
    if not account:
        raise HTTPException(
            400,
            f"Device '{device.name}' has no account for platform '{assignment.platform}'. "
            f"Create one at POST /api/device-accounts first.",
        )

    # Check platform is supported
    template_name = _PLATFORM_TEMPLATES.get(assignment.platform)
    if not template_name:
        raise HTTPException(
            400,
            f"Platform '{assignment.platform}' does not have an upload script yet. "
            f"Supported: {', '.join(_PLATFORM_TEMPLATES.keys())}",
        )

    # --- 2. Atomic idempotency via upload_status ---
    # Fast-path: re-use existing running task if linked via task_id
    if assignment.task_id:
        existing_task = session.get(Task, assignment.task_id)
        if existing_task and existing_task.status in (
            TaskStatus.PENDING, TaskStatus.RUNNING
        ):
            raise HTTPException(
                409,
                f"Assignment {assignment_id} already has a {existing_task.status.value} "
                f"task (task_id={existing_task.id}). Cancel it first or wait for completion.",
            )

    if (
        assignment.upload_status in (UploadStatus.UPLOAD_FAILED, UploadStatus.VERIFY_FAILED)
        and assignment.last_run_at
        and not opts.force
    ):
        last_run_at = assignment.last_run_at
        if last_run_at.tzinfo is None:
            last_run_at = last_run_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_run_at).total_seconds()
        cooldown_seconds = 120
        if elapsed < cooldown_seconds:
            remaining = int(cooldown_seconds - elapsed)
            raise HTTPException(
                409,
                f"Assignment {assignment_id} failed recently. Wait {remaining}s or retry with force=true.",
            )

    # --- 3. Auto-push if needed ---
    if assignment.push_status == PushStatus.PENDING and opts.auto_push:
        success, msg = await video_service.push_to_device(session, assignment_id)
        if not success:
            assignment.upload_status = UploadStatus.UPLOAD_FAILED
            assignment.last_error = f"Auto-push failed: {msg}"
            assignment.last_run_at = datetime.now(timezone.utc)
            session.add(assignment)
            session.commit()
            raise HTTPException(500, f"Auto-push failed: {msg}")
        # Refresh assignment after push updated it
        session.refresh(assignment)

    if assignment.push_status not in (PushStatus.PUSHED, PushStatus.UPLOADED):
        raise HTTPException(
            400,
            f"Video not pushed to device (push_status={assignment.push_status.value}). "
            f"Push first or set auto_push=true.",
        )

    # --- 4. Build template_vars — include device_path to bind exact file ---
    template_vars: dict = {
        "assignment_id": assignment.id,
        "video_id": assignment.video_id,
    }
    if assignment.device_path:
        # Pass the filename portion so the script can match by name in gallery
        from pathlib import PurePosixPath
        template_vars["device_path"] = assignment.device_path
        template_vars["device_filename"] = PurePosixPath(assignment.device_path).name

    # --- 5. Claim QUEUED slot atomically + create/link task ---
    # This prevents duplicate task creation when two requests race concurrently.
    now = datetime.now(timezone.utc)
    claim_stmt = (
        update(VideoAssignment)
        .where(VideoAssignment.id == assignment_id)
        .where(VideoAssignment.upload_status.notin_([UploadStatus.QUEUED, UploadStatus.RUNNING]))  # type: ignore
        .values(
            upload_status=UploadStatus.QUEUED,
            last_run_at=now,
            last_error=None,
        )
    )
    claim_result = session.exec(claim_stmt)
    if claim_result.rowcount != 1:
        session.rollback()
        raise HTTPException(
            409,
            f"Assignment {assignment_id} is already queued/running by another request.",
        )
    session.refresh(assignment)

    task = Task(
        device_id=assignment.device_id,
        command=f"Upload video to {assignment.platform} (assignment #{assignment.id})",
        template=template_name,
        execution_mode="script",
        max_steps=50,
        max_retries=1,
        assignment_id=assignment.id,
    )
    task.template_vars = template_vars

    session.add(task)
    session.flush()  # Get task.id before commit
    assignment.task_id = task.id
    session.add(assignment)
    session.commit()
    session.refresh(task)

    # --- 6. Submit to queue ---
    await task_queue.submit(task.id)

    logger.info(
        f"🚀 Upload job created: assignment={assignment_id} "
        f"task={task.id} platform={assignment.platform} "
        f"device={device.name}"
    )

    return {
        "success": True,
        "task_id": task.id,
        "assignment_id": assignment_id,
        "platform": assignment.platform,
        "upload_status": assignment.upload_status.value,
        "device": device.name,
        "message": f"Upload task #{task.id} queued for {assignment.platform}",
    }



@router.post("/assignments/run-batch")
async def run_batch_upload(
    body: RunBatchUploadRequest,
    session: Session = Depends(get_session),
):
    """Batch run-upload for multiple assignments.

    Body: { "assignment_ids": [1, 2, 3], "auto_push": true }
    Returns results per assignment (some may succeed, some may fail).
    """
    results = []
    for aid in body.assignment_ids:
        try:
            result = await run_upload(
                assignment_id=aid,
                body=RunUploadRequest(auto_push=body.auto_push, force=body.force),
                session=session,
            )
            results.append({"assignment_id": aid, "success": True, **result})
        except HTTPException as e:
            results.append({
                "assignment_id": aid,
                "success": False,
                "error": e.detail,
            })

    succeeded = sum(1 for r in results if r["success"])
    return {
        "total": len(body.assignment_ids),
        "succeeded": succeeded,
        "failed": len(body.assignment_ids) - succeeded,
        "results": results,
    }


@router.post("/{video_id}/ai-suggest")
async def ai_suggest_metadata(
    video_id: int,
    body: dict = None,
    session: Session = Depends(get_session),
):
    """Generate or retrieve cached AI metadata suggestions.

    Body: { "platform": "tiktok", "language": "vi", "force": false }
    - force=false (default): returns cached result if exists (0 tokens)
    - force=true: regenerate even if cached
    Response includes "cached": true/false indicator.
    """
    opts = body or {}
    platform = opts.get("platform", "tiktok")
    language = opts.get("language", "vi")
    force = opts.get("force", False)

    result = await ai_metadata_service.generate_suggestions(
        session,
        video_id,
        platform=str(platform).lower(),
        language=str(language).lower(),
        force=bool(force),
    )
    if result is None:
        raise HTTPException(
            500,
            "AI metadata generation failed. Check server logs for details.",
        )
    return result


@router.get("/{video_id}/ai-cache")
def get_ai_cache(
    video_id: int,
    session: Session = Depends(get_session),
):
    """List all cached AI metadata for a video (all languages/platforms)."""
    return ai_metadata_service.get_all_cached(session, video_id)


@router.get("/{video_id}/thumbnail")
def get_video_thumbnail(
    video_id: int,
    session: Session = Depends(get_session),
):
    """Serve AI-generated thumbnail for a video."""
    video = session.get(Video, video_id)
    if not video or not video.thumbnail:
        raise HTTPException(404, "Thumbnail not found")

    from pathlib import Path
    thumb_path = Path(video.thumbnail)
    if not thumb_path.exists():
        raise HTTPException(404, "Thumbnail file missing")

    from fastapi.responses import FileResponse
    return FileResponse(
        str(thumb_path),
        media_type="image/jpeg",
        filename=f"thumb_{video_id}.jpg",
    )


@router.post("/{video_id}/apply-ai")
def apply_ai_suggestions(
    video_id: int,
    body: dict = None,
    session: Session = Depends(get_session),
):
    """Apply AI suggestions to actual video fields.

    Body (optional): { "apply_title": true, "apply_tags": true, "apply_description": true }
    All default to true.
    """
    opts = body or {}
    result = ai_metadata_service.apply_suggestions(
        session,
        video_id,
        apply_title=opts.get("apply_title", True),
        apply_tags=opts.get("apply_tags", True),
        apply_description=opts.get("apply_description", True),
    )
    if result is None:
        raise HTTPException(404, "Video not found or no AI suggestions available")
    return result


# --- Dynamic {video_id} routes last ---

@router.get("/{video_id}")
def get_video(video_id: int, session: Session = Depends(get_session)):
    """Get video detail with all assignments."""
    video = video_service.get_video(session, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    return video


@router.delete("/{video_id}", status_code=204)
def delete_video(video_id: int, session: Session = Depends(get_session)):
    """Soft-delete a video (status → archived)."""
    if not video_service.delete_video(session, video_id):
        raise HTTPException(404, "Video not found")


@router.post("/{video_id}/assign", status_code=201)
def assign_video(
    video_id: int,
    body: dict,
    session: Session = Depends(get_session),
):
    """Assign a video to a device/platform.

    Body: { "device_id": int, "platform": "tiktok" }

    Returns 409 if the same video is already assigned to this platform.
    """
    device_id = body.get("device_id")
    platform = body.get("platform")

    if not device_id or not platform:
        raise HTTPException(400, "device_id and platform are required")

    assignment, error = video_service.assign_video(
        session, video_id, int(device_id), str(platform).lower()
    )
    if error:
        if "not found" in error:
            raise HTTPException(404, error)
        raise HTTPException(409, error)

    return assignment


# =============================================================================
# Device Account endpoints
# =============================================================================


@account_router.get("")
def list_device_accounts(
    device_id: Optional[int] = None,
    platform: Optional[str] = None,
    session: Session = Depends(get_session),
):
    """List device ↔ account mappings."""
    return video_service.get_device_accounts(
        session, device_id=device_id, platform=platform
    )


@account_router.post("", status_code=201)
def upsert_device_account(
    body: dict,
    session: Session = Depends(get_session),
):
    """Create or update a device-account mapping.

    Body: { "device_id": int, "platform": str, "account_name": str?, "notes": str? }
    """
    device_id = body.get("device_id")
    platform = body.get("platform")
    if not device_id or not platform:
        raise HTTPException(400, "device_id and platform are required")

    return video_service.upsert_device_account(
        session,
        device_id=int(device_id),
        platform=str(platform).lower(),
        account_name=body.get("account_name"),
        notes=body.get("notes"),
    )


@account_router.delete("/{account_id}", status_code=204)
def delete_device_account(
    account_id: int,
    session: Session = Depends(get_session),
):
    """Delete a device-account mapping."""
    from sqlmodel import select
    from app.models import DeviceAccount

    account = session.get(DeviceAccount, account_id)
    if not account:
        raise HTTPException(404, "Account mapping not found")
    session.delete(account)
    session.commit()
