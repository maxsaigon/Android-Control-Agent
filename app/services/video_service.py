"""Video management service — upload, assign, dedup, adb push."""

import hashlib
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlmodel import Session, select

from app.config import settings
from app.models import (
    Device,
    Task,
    TaskStatus,
    PushStatus,
    UploadStatus,
    Video,
    VideoAssignment,
    VideoStatus,
    DeviceAccount,
)
from app.services.upload_artifacts import upload_artifacts_service

logger = logging.getLogger(__name__)


def _sha256(path: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _video_to_dict(v: Video) -> dict:
    return {
        "id": v.id,
        "filename": v.filename,
        "filepath": v.filepath,
        "file_hash": v.file_hash,
        "file_size": v.file_size,
        "duration": v.duration,
        "title": v.title,
        "tags": v.tags,
        "description": v.description,
        "status": v.status,
        "file_cleaned_at": v.file_cleaned_at,
        "ai_title": v.ai_title,
        "ai_tags": v.ai_tags,
        "ai_description": v.ai_description,
        "ai_generated_at": v.ai_generated_at,
        "thumbnail": v.thumbnail,
        "created_at": v.created_at,
    }


def _serialize_account(account: DeviceAccount, device: Optional[Device]) -> dict:
    return {
        "device_id": account.device_id,
        "device_name": device.name if device else None,
        "device_status": device.status if device else None,
        "platform": account.platform,
        "account_name": account.account_name,
        "account_notes": account.notes,
    }


def _normalized_push_status(value: Optional[str]) -> str:
    if value == PushStatus.FAILED:
        return PushStatus.PUSH_FAILED
    return value or PushStatus.PENDING


def _can_push_assignment(a: VideoAssignment) -> bool:
    return _normalized_push_status(a.push_status) in {
        PushStatus.PENDING,
        PushStatus.PUSH_FAILED,
    }


def _can_run_upload(a: VideoAssignment, task: Optional[Task]) -> bool:
    if task and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
        return False
    if _normalized_push_status(a.push_status) not in {
        PushStatus.PUSHED,
        PushStatus.UPLOADED,
    }:
        return False
    return a.upload_status not in {
        "queued",
        "running",
        "uploaded",
    }


def _classify_error_hint(error: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not error:
        return None, None

    lowered = error.lower()
    if any(token in lowered for token in ("adb", "device offline", "connection", "timeout", "connect")):
        return "connectivity", "Kiểm tra ADB/device connectivity trước khi rerun"
    if any(token in lowered for token in ("gallery", "select video", "filename", "media picker")):
        return "gallery_select", "TikTok có thể chọn sai video trong gallery, cần review artifact"
    if any(token in lowered for token in ("verify", "publish", "post", "completed_main_nav")):
        return "post_verify", "Flow post hoàn tất nhưng bước verify/completion cần kiểm tra lại"
    return "generic", "Xem task logs và artifact trước khi rerun"


def _rerun_policy(a: VideoAssignment) -> dict:
    failed_statuses = {"upload_failed", "verify_failed"}
    cooldown_seconds = 120
    remaining = 0
    if a.upload_status in failed_statuses and a.last_run_at:
        last_run_at = a.last_run_at
        if last_run_at.tzinfo is None:
            last_run_at = last_run_at.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - last_run_at).total_seconds()
        remaining = max(0, int(cooldown_seconds - elapsed))

    can_rerun = a.upload_status in failed_statuses and remaining == 0
    return {
        "can_rerun": can_rerun,
        "rerun_requires_confirm": a.upload_status in failed_statuses,
        "rerun_cooldown_remaining_sec": remaining,
    }


def _build_platform_summary(
    assignments: list[dict],
    eligible_accounts_by_platform: dict[str, list[dict]],
) -> dict[str, dict]:
    platforms = set(eligible_accounts_by_platform.keys()) | {item["platform"] for item in assignments}
    summary: dict[str, dict] = {}
    for platform in sorted(platforms):
        platform_assignments = [item for item in assignments if item["platform"] == platform]
        eligible_accounts = eligible_accounts_by_platform.get(platform, [])
        eligible_device_ids = {item["device_id"] for item in eligible_accounts}
        assigned_device_ids = {item["device_id"] for item in platform_assignments}
        missing_targets = [
            item for item in eligible_accounts if item["device_id"] not in assigned_device_ids
        ]
        uploaded_count = sum(1 for item in platform_assignments if item["upload_status"] == "uploaded")
        running_count = sum(1 for item in platform_assignments if item["upload_status"] in {"queued", "running"})
        failed_count = sum(1 for item in platform_assignments if item["upload_status"] in {"upload_failed", "verify_failed"})
        summary[platform] = {
            "eligible_targets": len(eligible_accounts),
            "assigned_targets": len(platform_assignments),
            "uploaded_targets": uploaded_count,
            "running_targets": running_count,
            "failed_targets": failed_count,
            "missing_targets": len(missing_targets),
            "missing_target_devices": missing_targets,
            "coverage_complete": bool(eligible_accounts) and len(platform_assignments) == len(eligible_accounts),
        }
    return summary


def _assignment_to_dict(
    a: VideoAssignment,
    *,
    video: Optional[Video] = None,
    device: Optional[Device] = None,
    account: Optional[DeviceAccount] = None,
    task: Optional[Task] = None,
    artifact: Optional[dict] = None,
) -> dict:
    push_status = _normalized_push_status(a.push_status)
    latest_error = a.last_error or a.error
    error_hint_code, error_hint_label = _classify_error_hint(latest_error)
    rerun_policy = _rerun_policy(a)
    return {
        "id": a.id,
        "video_id": a.video_id,
        "device_id": a.device_id,
        "platform": a.platform,
        "push_status": push_status,
        "upload_status": a.upload_status,
        "device_path": a.device_path,
        "pushed_at": a.pushed_at,
        "uploaded_at": a.uploaded_at,
        "task_id": a.task_id,
        "error": a.error,
        "last_error": a.last_error,
        "latest_error": latest_error,
        "last_run_at": a.last_run_at,
        "created_at": a.created_at,
        "video_title": video.title if video else None,
        "video_filename": video.filename if video else None,
        "video_description": video.description if video else None,
        "video_tags": video.tags if video else None,
        "device_name": device.name if device else None,
        "device_status": device.status if device else None,
        "device_model": device.device_model if device else None,
        "account_name": account.account_name if account else None,
        "account_notes": account.notes if account else None,
        "task_status": task.status if task else None,
        "task_result": task.result if task else None,
        "task_error": task.error if task else None,
        "can_push": _can_push_assignment(a),
        "can_run_upload": _can_run_upload(a, task),
        "needs_push": _can_push_assignment(a),
        "ready_to_upload": _normalized_push_status(a.push_status) in {
            PushStatus.PUSHED,
            PushStatus.UPLOADED,
        },
        "has_errors": bool(latest_error),
        "error_hint_code": error_hint_code,
        "error_hint_label": error_hint_label,
        **rerun_policy,
        "artifact_session": artifact.get("session_name") if artifact else None,
        "artifact_dir": artifact.get("artifact_dir") if artifact else None,
        "artifact_manifest_url": artifact.get("manifest_url") if artifact else None,
        "artifact_screenrecord_url": artifact.get("screenrecord_url") if artifact else None,
        "artifact_finished_at": artifact.get("finished_at") if artifact else None,
        "artifact_result": artifact.get("result") if artifact else None,
        "artifact_latest_snapshot": artifact.get("latest_snapshot") if artifact else None,
        "artifact_snapshots_count": artifact.get("snapshots_count", 0) if artifact else 0,
    }


class VideoService:
    """Service for managing video uploads, assignments, and ADB pushes."""

    def __init__(self) -> None:
        self._storage_dir = Path(settings.video_storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Upload
    # ------------------------------------------------------------------

    async def upload_video(
        self,
        session: Session,
        file: UploadFile,
        title: Optional[str] = None,
        tags: Optional[str] = None,
    ) -> tuple[dict, bool]:
        """Save uploaded video to storage directory.

        Returns:
            (video_dict, is_new) — is_new=False when duplicate detected.
        """
        # Write to a temp file first so we can hash before final move
        tmp_path = self._storage_dir / f"_tmp_{file.filename}"
        try:
            with open(tmp_path, "wb") as f:
                content = await file.read()
                f.write(content)

            file_hash = _sha256(str(tmp_path))
            file_size = os.path.getsize(str(tmp_path))

            # Deduplication check
            existing = session.exec(
                select(Video).where(Video.file_hash == file_hash)
            ).first()
            if existing:
                logger.info(f"Duplicate video detected: hash={file_hash[:12]} → id={existing.id}")
                os.remove(tmp_path)
                return _video_to_dict(existing), False

            # Move to final location using hash as filename stem
            ext = Path(file.filename).suffix
            final_name = f"{file_hash[:16]}{ext}"
            final_path = self._storage_dir / final_name
            shutil.move(str(tmp_path), str(final_path))

            video = Video(
                filename=file.filename,
                filepath=str(final_path),
                file_hash=file_hash,
                file_size=file_size,
                title=title or Path(file.filename).stem,
                tags=tags,
                status=VideoStatus.AVAILABLE,
            )
            session.add(video)
            session.commit()
            session.refresh(video)
            logger.info(f"Video uploaded: id={video.id} file={final_name}")
            return _video_to_dict(video), True

        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_videos(
        self,
        session: Session,
        status: Optional[str] = None,
        platform: Optional[str] = None,
        unassigned_only: bool = False,
    ) -> list[dict]:
        """List videos with optional filters."""
        stmt = select(Video)
        if status:
            stmt = stmt.where(Video.status == status)
        else:
            stmt = stmt.where(Video.status == VideoStatus.AVAILABLE)

        videos = session.exec(stmt).all()

        if platform and unassigned_only:
            # Exclude videos that already have an assignment for this platform
            assigned_ids = {
                a.video_id
                for a in session.exec(
                    select(VideoAssignment).where(VideoAssignment.platform == platform)
                ).all()
            }
            videos = [v for v in videos if v.id not in assigned_ids]

        assignments = session.exec(select(VideoAssignment)).all()
        all_accounts = session.exec(select(DeviceAccount)).all()
        assignment_by_video: dict[int, list[VideoAssignment]] = {}
        for assignment in assignments:
            assignment_by_video.setdefault(assignment.video_id, []).append(assignment)

        device_ids = {a.device_id for a in assignments}
        device_ids.update(account.device_id for account in all_accounts)
        task_ids = {a.task_id for a in assignments if a.task_id}
        account_keys = {(a.device_id, a.platform) for a in assignments}

        device_map = {
            d.id: d for d in session.exec(
                select(Device).where(Device.id.in_(device_ids))  # type: ignore[arg-type]
            ).all()
        } if device_ids else {}
        task_map = {
            t.id: t for t in session.exec(
                select(Task).where(Task.id.in_(task_ids))  # type: ignore[arg-type]
            ).all()
        } if task_ids else {}
        account_map = {
            (a.device_id, a.platform): a
            for a in all_accounts
            if (a.device_id, a.platform) in account_keys
        }
        eligible_accounts_by_platform: dict[str, list[dict]] = {}
        for account in all_accounts:
            eligible_accounts_by_platform.setdefault(account.platform, []).append(
                _serialize_account(account, device_map.get(account.device_id))
            )
        artifact_index = upload_artifacts_service.build_assignment_index()

        result = []
        for v in videos:
            d = _video_to_dict(v)
            video_assignments = assignment_by_video.get(v.id, [])
            d["assignments"] = [
                _assignment_to_dict(
                    a,
                    video=v,
                    device=device_map.get(a.device_id),
                    account=account_map.get((a.device_id, a.platform)),
                    task=task_map.get(a.task_id),
                    artifact=artifact_index.get(a.id or -1),
                )
                for a in video_assignments
            ]
            d["assignment_count"] = len(video_assignments)
            d["platform_summary"] = _build_platform_summary(
                d["assignments"],
                eligible_accounts_by_platform,
            )
            d["tiktok_assignments"] = [
                assignment for assignment in d["assignments"] if assignment["platform"] == "tiktok"
            ]
            d["tiktok_assignment"] = d["tiktok_assignments"][0] if d["tiktok_assignments"] else None
            result.append(d)
        return result

    def get_video(self, session: Session, video_id: int) -> Optional[dict]:
        """Get video detail with assignments."""
        video = session.get(Video, video_id)
        if not video:
            return None
        assignments = session.exec(
            select(VideoAssignment).where(VideoAssignment.video_id == video.id)
        ).all()
        device_ids = {a.device_id for a in assignments}
        task_ids = {a.task_id for a in assignments if a.task_id}
        device_map = {
            d.id: d for d in session.exec(
                select(Device).where(Device.id.in_(device_ids))  # type: ignore[arg-type]
            ).all()
        } if device_ids else {}
        task_map = {
            t.id: t for t in session.exec(
                select(Task).where(Task.id.in_(task_ids))  # type: ignore[arg-type]
            ).all()
        } if task_ids else {}
        all_accounts = session.exec(select(DeviceAccount)).all()
        account_map = {
            (a.device_id, a.platform): a
            for a in all_accounts
        }
        eligible_accounts_by_platform: dict[str, list[dict]] = {}
        for account in all_accounts:
            eligible_accounts_by_platform.setdefault(account.platform, []).append(
                _serialize_account(account, device_map.get(account.device_id))
            )
        artifact_index = upload_artifacts_service.build_assignment_index()
        d = _video_to_dict(video)
        d["assignments"] = [
            _assignment_to_dict(
                a,
                video=video,
                device=device_map.get(a.device_id),
                account=account_map.get((a.device_id, a.platform)),
                task=task_map.get(a.task_id),
                artifact=artifact_index.get(a.id or -1),
            )
            for a in assignments
        ]
        d["assignment_count"] = len(d["assignments"])
        d["platform_summary"] = _build_platform_summary(
            d["assignments"],
            eligible_accounts_by_platform,
        )
        d["tiktok_assignments"] = [
            assignment for assignment in d["assignments"] if assignment["platform"] == "tiktok"
        ]
        d["tiktok_assignment"] = d["tiktok_assignments"][0] if d["tiktok_assignments"] else None
        return d

    def get_assignments(
        self,
        session: Session,
        video_id: Optional[int] = None,
        device_id: Optional[int] = None,
        platform: Optional[str] = None,
        push_status: Optional[str] = None,
        upload_status: Optional[str] = None,
        actionable_only: bool = False,
    ) -> list[dict]:
        """Get full assignment matrix, optionally filtered."""
        stmt = select(VideoAssignment)
        if video_id:
            stmt = stmt.where(VideoAssignment.video_id == video_id)
        if device_id:
            stmt = stmt.where(VideoAssignment.device_id == device_id)
        if platform:
            stmt = stmt.where(VideoAssignment.platform == platform)
        if push_status:
            if push_status == PushStatus.PUSH_FAILED:
                stmt = stmt.where(
                    VideoAssignment.push_status.in_([PushStatus.PUSH_FAILED, PushStatus.FAILED])  # type: ignore[arg-type]
                )
            else:
                stmt = stmt.where(VideoAssignment.push_status == push_status)
        if upload_status:
            stmt = stmt.where(VideoAssignment.upload_status == upload_status)

        assignments = session.exec(stmt).all()
        assignments.sort(key=lambda a: (a.created_at, a.id or 0), reverse=True)

        video_ids = {a.video_id for a in assignments}
        device_ids = {a.device_id for a in assignments}
        task_ids = {a.task_id for a in assignments if a.task_id}

        video_map = {
            v.id: v for v in session.exec(
                select(Video).where(Video.id.in_(video_ids))  # type: ignore[arg-type]
            ).all()
        } if video_ids else {}
        device_map = {
            d.id: d for d in session.exec(
                select(Device).where(Device.id.in_(device_ids))  # type: ignore[arg-type]
            ).all()
        } if device_ids else {}
        task_map = {
            t.id: t for t in session.exec(
                select(Task).where(Task.id.in_(task_ids))  # type: ignore[arg-type]
            ).all()
        } if task_ids else {}
        account_map = {
            (account.device_id, account.platform): account
            for account in session.exec(select(DeviceAccount)).all()
        }
        artifact_index = upload_artifacts_service.build_assignment_index()

        result = [
            _assignment_to_dict(
                assignment,
                video=video_map.get(assignment.video_id),
                device=device_map.get(assignment.device_id),
                account=account_map.get((assignment.device_id, assignment.platform)),
                task=task_map.get(assignment.task_id),
                artifact=artifact_index.get(assignment.id or -1),
            )
            for assignment in assignments
        ]
        if actionable_only:
            result = [
                item for item in result
                if item["can_push"] or item["can_run_upload"]
            ]
        return result

    # ------------------------------------------------------------------
    # Assign
    # ------------------------------------------------------------------

    def assign_video(
        self,
        session: Session,
        video_id: int,
        device_id: int,
        platform: str,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Assign a video to a device/platform.

        Returns:
            (assignment_dict, None) on success
            (None, error_message) on failure
        """
        video = session.get(Video, video_id)
        if not video or video.status == VideoStatus.ARCHIVED:
            return None, "Video not found or archived"

        device = session.get(Device, device_id)
        if not device:
            return None, "Device not found"

        # UNIQUE(video_id, device_id, platform) check — 1 target per device/platform
        existing = session.exec(
            select(VideoAssignment).where(
                VideoAssignment.video_id == video_id,
                VideoAssignment.device_id == device_id,
                VideoAssignment.platform == platform,
            )
        ).first()
        if existing:
            return None, (
                f"Video đã được assign cho device '{device.name}' "
                f"trên platform '{platform}' (assignment #{existing.id})"
            )

        assignment = VideoAssignment(
            video_id=video_id,
            device_id=device_id,
            platform=platform,
            push_status=PushStatus.PENDING,
        )
        session.add(assignment)
        session.commit()
        session.refresh(assignment)
        logger.info(
            f"Video {video_id} assigned → device {device_id} "
            f"platform={platform} assignment_id={assignment.id}"
        )
        return _assignment_to_dict(assignment), None

    def auto_assign(
        self,
        session: Session,
        platform: str,
        video_ids: Optional[list[int]] = None,
    ) -> list[dict]:
        """Assign videos to every eligible device/account target that is still missing.

        Each device must have a DeviceAccount for the platform.
        """
        # Get candidate devices (those with an account for this platform)
        device_accounts = session.exec(
            select(DeviceAccount).where(DeviceAccount.platform == platform)
        ).all()
        if not device_accounts:
            return []

        device_ids = sorted({da.device_id for da in device_accounts})

        # Get candidate videos
        if video_ids:
            videos = [session.get(Video, vid) for vid in video_ids if session.get(Video, vid)]
        else:
            videos = session.exec(
                select(Video).where(Video.status == VideoStatus.AVAILABLE)
            ).all()

        existing_assignments = session.exec(
            select(VideoAssignment).where(VideoAssignment.platform == platform)
        ).all()
        existing_pairs = {
            (assignment.video_id, assignment.device_id)
            for assignment in existing_assignments
        }

        candidates = [v for v in videos if v and v.status == VideoStatus.AVAILABLE]
        if not candidates:
            return []

        created = []
        for video in candidates:
            for device_id in device_ids:
                if (video.id, device_id) in existing_pairs:
                    continue
                assignment = VideoAssignment(
                    video_id=video.id,
                    device_id=device_id,
                    platform=platform,
                    push_status=PushStatus.PENDING,
                )
                session.add(assignment)
                created.append(assignment)
                existing_pairs.add((video.id, device_id))

        session.commit()
        for a in created:
            session.refresh(a)
        logger.info(
            "Auto-assigned %s missing targets for platform=%s across %s videos",
            len(created),
            platform,
            len(candidates),
        )
        return [_assignment_to_dict(a) for a in created]

    def update_assignment(
        self,
        session: Session,
        assignment_id: int,
        *,
        device_id: Optional[int] = None,
        platform: Optional[str] = None,
    ) -> tuple[Optional[dict], Optional[str]]:
        """Move an assignment to a different device/platform target."""
        assignment = session.get(VideoAssignment, assignment_id)
        if not assignment:
            return None, "Assignment not found"

        task = session.get(Task, assignment.task_id) if assignment.task_id else None
        if task and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            return None, (
                f"Assignment #{assignment_id} đang có task {task.status.value}. "
                "Hãy chờ hoàn tất hoặc cancel trước khi sửa target."
            )
        if assignment.upload_status in {UploadStatus.QUEUED, UploadStatus.RUNNING}:
            return None, (
                f"Assignment #{assignment_id} đang ở trạng thái {assignment.upload_status.value}. "
                "Không thể sửa target lúc này."
            )

        target_device_id = int(device_id) if device_id is not None else assignment.device_id
        target_platform = str(platform).lower() if platform else assignment.platform
        device = session.get(Device, target_device_id)
        if not device:
            return None, "Device not found"

        existing = session.exec(
            select(VideoAssignment).where(
                VideoAssignment.video_id == assignment.video_id,
                VideoAssignment.device_id == target_device_id,
                VideoAssignment.platform == target_platform,
                VideoAssignment.id != assignment_id,
            )
        ).first()
        if existing:
            return None, (
                f"Video đã được assign cho device '{device.name}' "
                f"trên platform '{target_platform}' (assignment #{existing.id})"
            )

        target_changed = (
            assignment.device_id != target_device_id
            or assignment.platform != target_platform
        )
        assignment.device_id = target_device_id
        assignment.platform = target_platform

        if target_changed:
            # Runtime state belongs to the old target and must be rebuilt.
            assignment.push_status = PushStatus.PENDING
            assignment.upload_status = UploadStatus.PENDING
            assignment.device_path = None
            assignment.pushed_at = None
            assignment.uploaded_at = None
            assignment.task_id = None
            assignment.error = None
            assignment.last_error = None
            assignment.last_run_at = None

        session.add(assignment)
        session.commit()
        session.refresh(assignment)

        account = session.exec(
            select(DeviceAccount).where(
                DeviceAccount.device_id == assignment.device_id,
                DeviceAccount.platform == assignment.platform,
            )
        ).first()
        logger.info(
            "Updated assignment %s -> device=%s platform=%s target_changed=%s",
            assignment_id,
            assignment.device_id,
            assignment.platform,
            target_changed,
        )
        return _assignment_to_dict(
            assignment,
            device=device,
            account=account,
        ), None

    def delete_assignment(
        self,
        session: Session,
        assignment_id: int,
    ) -> Optional[str]:
        """Delete an assignment unless it is actively processing."""
        assignment = session.get(VideoAssignment, assignment_id)
        if not assignment:
            return "Assignment not found"

        task = session.get(Task, assignment.task_id) if assignment.task_id else None
        if task and task.status in {TaskStatus.PENDING, TaskStatus.RUNNING}:
            return (
                f"Assignment #{assignment_id} đang có task {task.status.value}. "
                "Hãy chờ hoàn tất hoặc cancel trước khi xóa."
            )
        if assignment.upload_status in {UploadStatus.QUEUED, UploadStatus.RUNNING}:
            return (
                f"Assignment #{assignment_id} đang ở trạng thái {assignment.upload_status.value}. "
                "Không thể xóa lúc này."
            )

        session.delete(assignment)
        session.commit()
        logger.info("Deleted assignment %s", assignment_id)
        return None

    # ------------------------------------------------------------------
    # ADB Push
    # ------------------------------------------------------------------

    async def push_to_device(
        self,
        session: Session,
        assignment_id: int,
    ) -> tuple[bool, str]:
        """ADB push video file to device.

        Returns:
            (success, message)
        """
        assignment = session.get(VideoAssignment, assignment_id)
        if not assignment:
            return False, "Assignment not found"

        video = session.get(Video, assignment.video_id)
        if not video:
            return False, "Video record not found"

        device = session.get(Device, assignment.device_id)
        if not device:
            return False, "Device not found"

        # Validate file exists on server
        if not os.path.exists(video.filepath):
            assignment.push_status = PushStatus.PUSH_FAILED
            assignment.error = "Source file not found on server"
            session.commit()
            return False, assignment.error

        # Determine destination path
        target_dir = settings.device_video_path
        filename = Path(video.filepath).name
        device_path = f"{target_dir}/{filename}"

        adb_target = f"{device.ip_address}:{device.adb_port}"

        try:
            # Step 0: Ensure ADB connection (WiFi ADB can drop)
            connect_cmd = [
                settings.adb_path, "connect", adb_target,
            ]
            logger.info(f"ADB connect: {adb_target}")
            conn_result = subprocess.run(
                connect_cmd, capture_output=True, text=True, timeout=10
            )
            conn_output = (conn_result.stdout + conn_result.stderr).strip()
            logger.info(f"ADB connect result: {conn_output}")

            # Ensure target directory exists on device
            mkdir_cmd = [
                settings.adb_path, "-s", adb_target,
                "shell", f"mkdir -p {target_dir}",
            ]
            logger.info(f"ADB mkdir: {' '.join(mkdir_cmd)}")
            subprocess.run(mkdir_cmd, capture_output=True, timeout=10)

            # Push the file (with retry on failure)
            push_cmd = [
                settings.adb_path, "-s", adb_target,
                "push", video.filepath, device_path,
            ]
            logger.info(
                f"ADB push: {video.filepath} → {adb_target}:{device_path}"
            )
            result = subprocess.run(
                push_cmd, capture_output=True, text=True, timeout=300
            )

            # If first attempt fails, retry with fresh connect
            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                logger.warning(
                    f"ADB push attempt 1 failed: {error_msg}. Retrying with fresh connect..."
                )

                # Force reconnect
                subprocess.run(
                    [settings.adb_path, "disconnect", adb_target],
                    capture_output=True, timeout=5,
                )
                time.sleep(1)
                subprocess.run(
                    connect_cmd, capture_output=True, text=True, timeout=10
                )
                time.sleep(1)

                # Retry push
                result = subprocess.run(
                    push_cmd, capture_output=True, text=True, timeout=300
                )

            if result.returncode != 0:
                error_msg = result.stderr.strip() or result.stdout.strip()
                assignment.push_status = PushStatus.PUSH_FAILED
                assignment.error = error_msg
                session.commit()
                logger.error(f"ADB push failed: {error_msg}")
                return False, f"ADB push failed: {error_msg}"

            # Success — scan media so gallery picks it up
            scan_cmd = [
                settings.adb_path, "-s", adb_target,
                "shell", f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
                         f"-d file://{device_path}",
            ]
            subprocess.run(scan_cmd, capture_output=True, timeout=10)

            assignment.push_status = PushStatus.PUSHED
            assignment.device_path = device_path
            assignment.pushed_at = datetime.now(timezone.utc)
            assignment.error = None
            session.commit()

            logger.info(
                f"Push success: assignment {assignment_id} → {adb_target}:{device_path}"
            )
            return True, f"Pushed to {device.name}:{device_path}"

        except subprocess.TimeoutExpired:
            assignment.push_status = PushStatus.PUSH_FAILED
            assignment.error = "ADB push timeout (>300s)"
            session.commit()
            return False, assignment.error
        except Exception as e:
            assignment.push_status = PushStatus.PUSH_FAILED
            assignment.error = str(e)
            session.commit()
            logger.exception("Unexpected error during ADB push")
            return False, str(e)

    # ------------------------------------------------------------------
    # Soft-delete
    # ------------------------------------------------------------------

    def delete_video(self, session: Session, video_id: int) -> bool:
        """Soft-delete a video (status → archived)."""
        video = session.get(Video, video_id)
        if not video:
            return False
        video.status = VideoStatus.ARCHIVED
        session.commit()
        logger.info(f"Video {video_id} archived")
        return True

    # ------------------------------------------------------------------
    # Device Accounts
    # ------------------------------------------------------------------

    def get_device_accounts(
        self,
        session: Session,
        device_id: Optional[int] = None,
        platform: Optional[str] = None,
    ) -> list[dict]:
        """List device-account mappings."""
        stmt = select(DeviceAccount)
        if device_id:
            stmt = stmt.where(DeviceAccount.device_id == device_id)
        if platform:
            stmt = stmt.where(DeviceAccount.platform == platform)
        accounts = session.exec(stmt).all()
        device_ids = {a.device_id for a in accounts}
        device_map = {
            d.id: d for d in session.exec(
                select(Device).where(Device.id.in_(device_ids))  # type: ignore[arg-type]
            ).all()
        } if device_ids else {}
        return [
            {
                "id": a.id,
                "device_id": a.device_id,
                "device_name": device_map.get(a.device_id).name if device_map.get(a.device_id) else None,
                "platform": a.platform,
                "account_name": a.account_name,
                "notes": a.notes,
                "created_at": a.created_at,
            }
            for a in accounts
        ]

    def upsert_device_account(
        self,
        session: Session,
        device_id: int,
        platform: str,
        account_name: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """Create or update a device-account mapping."""
        existing = session.exec(
            select(DeviceAccount).where(
                DeviceAccount.device_id == device_id,
                DeviceAccount.platform == platform,
            )
        ).first()

        if existing:
            existing.account_name = account_name
            existing.notes = notes
            session.commit()
            session.refresh(existing)
            account = existing
        else:
            account = DeviceAccount(
                device_id=device_id,
                platform=platform,
                account_name=account_name,
                notes=notes,
            )
            session.add(account)
            session.commit()
            session.refresh(account)

        logger.info(
            f"DeviceAccount upserted: device={device_id} platform={platform} "
            f"account={account_name}"
        )
        return {
            "id": account.id,
            "device_id": account.device_id,
            "platform": account.platform,
            "account_name": account.account_name,
            "notes": account.notes,
            "created_at": account.created_at,
        }

    # ------------------------------------------------------------------
    # Auto-cleanup: delete physical files after push (keep DB records)
    # ------------------------------------------------------------------

    def cleanup_pushed_videos(
        self,
        session: Session,
        max_age_days: int = 3,
    ) -> int:
        """Delete physical video files that have been pushed to all assigned
        devices more than `max_age_days` ago.

        DB records (Video + VideoAssignment) are preserved — only the
        file on disk is removed to free storage.

        Returns:
            Number of files cleaned up.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        cleaned = 0

        videos = session.exec(
            select(Video).where(
                Video.status == VideoStatus.AVAILABLE,
                Video.file_cleaned_at == None,  # noqa: E711  (SQLAlchemy IS NULL)
            )
        ).all()

        for video in videos:
            # Get all assignments for this video
            assignments = session.exec(
                select(VideoAssignment).where(
                    VideoAssignment.video_id == video.id
                )
            ).all()

            # Skip if no assignments at all
            if not assignments:
                continue

            # ALL assignments must be pushed/uploaded (not pending/failed)
            all_pushed = all(
                a.push_status in (PushStatus.PUSHED, PushStatus.UPLOADED)
                for a in assignments
            )
            if not all_pushed:
                continue

            # Check if the LATEST push was > max_age_days ago
            latest_push = max(
                (a.pushed_at for a in assignments if a.pushed_at),
                default=None,
            )
            if not latest_push or latest_push > cutoff:
                continue

            # Safe to delete physical file
            filepath = video.filepath
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    logger.info(
                        f"🗑️ Cleaned video file: {filepath} "
                        f"(id={video.id}, pushed {max_age_days}+ days ago)"
                    )
                except OSError as e:
                    logger.warning(f"Failed to clean {filepath}: {e}")
                    continue

            video.file_cleaned_at = datetime.now(timezone.utc)
            cleaned += 1

        if cleaned:
            session.commit()
            logger.info(f"🗑️ Video cleanup: {cleaned} files removed")

        return cleaned


# Singleton
video_service = VideoService()
