"""Helper APK release metadata and artifact resolution."""

from __future__ import annotations

import json
from pathlib import Path

HELPER_LATEST_ALIAS = "android-control-helper-latest.apk"
HELPER_METADATA_FILE = "helper-release.json"
LEGACY_HELPER_ALIAS = "ac-helper.apk"


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def helper_downloads_dir() -> Path:
    return _repo_root() / "app" / "static" / "downloads"


def helper_release_metadata_path() -> Path:
    return helper_downloads_dir() / HELPER_METADATA_FILE


def load_helper_release_metadata() -> dict | None:
    """Load helper release metadata if it has been published."""
    path = helper_release_metadata_path()
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def helper_apk_candidates() -> list[Path]:
    """Return helper APK candidates ordered by release priority."""
    downloads_dir = helper_downloads_dir()
    metadata = load_helper_release_metadata()
    candidates: list[Path] = []

    if metadata:
        artifact_name = metadata.get("artifact_name")
        latest_alias = metadata.get("latest_alias", HELPER_LATEST_ALIAS)
        if artifact_name:
            candidates.append(downloads_dir / artifact_name)
        if latest_alias:
            candidates.append(downloads_dir / latest_alias)

    candidates.extend(
        [
            downloads_dir / HELPER_LATEST_ALIAS,
            downloads_dir / LEGACY_HELPER_ALIAS,
            _repo_root()
            / "android-helper"
            / "app"
            / "build"
            / "outputs"
            / "apk"
            / "debug"
            / "app-debug.apk",
        ]
    )

    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        ordered.append(candidate)
    return ordered


def resolve_helper_apk_path() -> Path | None:
    """Resolve the best available helper APK path."""
    for candidate in helper_apk_candidates():
        if candidate.exists():
            return candidate
    return None


def helper_download_filename() -> str:
    """Filename presented to the browser when downloading the helper."""
    metadata = load_helper_release_metadata() or {}
    resolved = resolve_helper_apk_path()
    return metadata.get("artifact_name") or (resolved.name if resolved else HELPER_LATEST_ALIAS)
