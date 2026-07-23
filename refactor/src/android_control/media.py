"""Media catalog and device transfer."""

import hashlib
import re
import uuid
from pathlib import Path

from fastapi import UploadFile

from .database import Repository
from .models import MediaView, utc_now


class MediaService:
    def __init__(self, repository: Repository, storage_dir: Path):
        self.repository = repository
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def save(self, upload: UploadFile) -> MediaView:
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", upload.filename or "media.bin")
        media_id = uuid.uuid4().hex[:12]
        target = self.storage_dir / f"{media_id}-{safe_name}"
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as output:
            while chunk := await upload.read(1024 * 1024):
                output.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        item = {
            "id": media_id,
            "filename": safe_name,
            "storage_path": str(target),
            "size_bytes": size,
            "sha256": digest.hexdigest(),
            "created_at": utc_now(),
        }
        self.repository.add_media(item)
        return MediaView(**item)
