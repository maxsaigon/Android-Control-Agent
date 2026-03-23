"""Video management API endpoints."""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlmodel import Session

from app.database import get_session
from app.services.video_service import video_service
from app.services.ai_metadata_service import ai_metadata_service

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
    session: Session = Depends(get_session),
):
    """Get full assignment matrix. Filter by video_id or device_id."""
    return video_service.get_assignments(session, video_id=video_id, device_id=device_id)


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


# --- AI Metadata endpoints (static paths, before dynamic /{video_id}) ---


@router.post("/{video_id}/ai-suggest")
async def ai_suggest_metadata(
    video_id: int,
    body: dict = None,
    session: Session = Depends(get_session),
):
    """Trigger AI metadata generation for a video.

    Body (optional): { "platform": "tiktok" }
    Default platform: tiktok
    """
    platform = (body or {}).get("platform", "tiktok")

    result = await ai_metadata_service.generate_suggestions(
        session, video_id, platform=str(platform).lower()
    )
    if result is None:
        raise HTTPException(
            500,
            "AI metadata generation failed. Check server logs for details.",
        )
    return result


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
