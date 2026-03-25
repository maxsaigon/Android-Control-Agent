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
    PushStatus,
    Video,
    VideoAssignment,
    VideoStatus,
    DeviceAccount,
)

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


def _assignment_to_dict(a: VideoAssignment) -> dict:
    return {
        "id": a.id,
        "video_id": a.video_id,
        "device_id": a.device_id,
        "platform": a.platform,
        "push_status": a.push_status,
        "upload_status": a.upload_status,
        "device_path": a.device_path,
        "pushed_at": a.pushed_at,
        "uploaded_at": a.uploaded_at,
        "task_id": a.task_id,
        "error": a.error,
        "last_error": a.last_error,
        "last_run_at": a.last_run_at,
        "created_at": a.created_at,
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

        result = []
        for v in videos:
            d = _video_to_dict(v)
            d["assignments"] = [
                _assignment_to_dict(a)
                for a in session.exec(
                    select(VideoAssignment).where(VideoAssignment.video_id == v.id)
                ).all()
            ]
            result.append(d)
        return result

    def get_video(self, session: Session, video_id: int) -> Optional[dict]:
        """Get video detail with assignments."""
        video = session.get(Video, video_id)
        if not video:
            return None
        d = _video_to_dict(video)
        d["assignments"] = [
            _assignment_to_dict(a)
            for a in session.exec(
                select(VideoAssignment).where(VideoAssignment.video_id == video.id)
            ).all()
        ]
        return d

    def get_assignments(
        self,
        session: Session,
        video_id: Optional[int] = None,
        device_id: Optional[int] = None,
    ) -> list[dict]:
        """Get full assignment matrix, optionally filtered."""
        stmt = select(VideoAssignment)
        if video_id:
            stmt = stmt.where(VideoAssignment.video_id == video_id)
        if device_id:
            stmt = stmt.where(VideoAssignment.device_id == device_id)
        return [_assignment_to_dict(a) for a in session.exec(stmt).all()]

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

        # UNIQUE(video_id, platform) check — 1 video per platform
        existing = session.exec(
            select(VideoAssignment).where(
                VideoAssignment.video_id == video_id,
                VideoAssignment.platform == platform,
            )
        ).first()
        if existing:
            # Find who owns it for a helpful message
            owner_device = session.get(Device, existing.device_id)
            owner_name = owner_device.name if owner_device else f"device #{existing.device_id}"
            return None, (
                f"Video đã được assign cho platform '{platform}' "
                f"bởi {owner_name} (assignment #{existing.id})"
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
        """Round-robin assign videos to devices that don't have them yet.

        Each device must have a DeviceAccount for the platform.
        """
        # Get candidate devices (those with an account for this platform)
        device_accounts = session.exec(
            select(DeviceAccount).where(DeviceAccount.platform == platform)
        ).all()
        if not device_accounts:
            return []

        device_ids = [da.device_id for da in device_accounts]

        # Get candidate videos
        if video_ids:
            videos = [session.get(Video, vid) for vid in video_ids if session.get(Video, vid)]
        else:
            videos = session.exec(
                select(Video).where(Video.status == VideoStatus.AVAILABLE)
            ).all()

        # Already assigned for this platform
        assigned_video_ids = {
            a.video_id
            for a in session.exec(
                select(VideoAssignment).where(VideoAssignment.platform == platform)
            ).all()
        }

        unassigned = [v for v in videos if v.id not in assigned_video_ids]
        if not unassigned:
            return []

        created = []
        for i, video in enumerate(unassigned):
            device_id = device_ids[i % len(device_ids)]
            assignment = VideoAssignment(
                video_id=video.id,
                device_id=device_id,
                platform=platform,
                push_status=PushStatus.PENDING,
            )
            session.add(assignment)
            created.append(assignment)

        session.commit()
        for a in created:
            session.refresh(a)
        logger.info(f"Auto-assigned {len(created)} videos for platform={platform}")
        return [_assignment_to_dict(a) for a in created]

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
        return [
            {
                "id": a.id,
                "device_id": a.device_id,
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
