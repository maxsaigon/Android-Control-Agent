"""Helpers for locating and serving TikTok upload debug artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from app.config import settings


class UploadArtifactsService:
    """Read upload artifact manifests and expose normalized summaries."""

    def __init__(self) -> None:
        self._root = Path(settings.screenshots_dir) / "tiktok_upload_debug"

    def _artifact_root(self) -> Path:
        return self._root

    def _file_url(self, session_name: str, filename: Optional[str]) -> Optional[str]:
        if not filename:
            return None
        return f"/debug-media/tiktok_upload_debug/{quote(session_name)}/{quote(filename)}"

    def _snapshot_summary(self, session_name: str, snapshot: dict) -> dict:
        screenshot_name = Path(snapshot.get("screenshot_path") or "").name or None
        xml_name = Path(snapshot.get("ui_xml_path") or "").name or None
        label = snapshot.get("label") or "snapshot"
        meta_name = f"{label}.json".replace(" ", "_")
        return {
            "label": label,
            "note": snapshot.get("note"),
            "timestamp": snapshot.get("timestamp"),
            "foreground_app": snapshot.get("foreground_app"),
            "screenshot_url": self._file_url(session_name, screenshot_name),
            "xml_url": self._file_url(session_name, xml_name),
            "meta_url": self._file_url(session_name, meta_name),
        }

    def _manifest_summary(self, manifest_path: Path, manifest: dict) -> dict:
        session_name = manifest_path.parent.name
        snapshots = [
            self._snapshot_summary(session_name, snapshot)
            for snapshot in manifest.get("snapshots", [])
        ]
        screenrecord = manifest.get("screenrecord") or {}
        screenrecord_name = Path(screenrecord.get("local_path") or "").name or None
        result = manifest.get("result") or {}
        return {
            "session_name": session_name,
            "assignment_id": manifest.get("assignment_id"),
            "video_id": manifest.get("video_id"),
            "device": manifest.get("device"),
            "started_at": manifest.get("started_at"),
            "finished_at": manifest.get("finished_at"),
            "result": result,
            "artifact_dir": str(manifest_path.parent),
            "manifest_url": self._file_url(session_name, manifest_path.name),
            "screenrecord_url": self._file_url(session_name, screenrecord_name),
            "snapshots_count": len(snapshots),
            "latest_snapshot": snapshots[-1] if snapshots else None,
            "snapshots": snapshots,
        }

    def list_recent(self) -> list[dict]:
        root = self._artifact_root()
        if not root.exists():
            return []

        manifests: list[tuple[float, dict]] = []
        for manifest_path in root.glob("*/manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                manifests.append((manifest_path.stat().st_mtime, self._manifest_summary(manifest_path, manifest)))
            except Exception:
                continue
        manifests.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in manifests]

    def build_assignment_index(self) -> dict[int, dict]:
        index: dict[int, dict] = {}
        for artifact in self.list_recent():
            assignment_id = artifact.get("assignment_id")
            if not assignment_id or assignment_id in index:
                continue
            index[int(assignment_id)] = artifact
        return index

    def find_assignment_artifact(self, assignment_id: int) -> Optional[dict]:
        return self.build_assignment_index().get(assignment_id)


upload_artifacts_service = UploadArtifactsService()
