#!/usr/bin/env python3
"""Publish the latest helper APK into app/static/downloads/ with metadata."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import subprocess

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "android-helper" / "app" / "build" / "outputs" / "apk" / "debug"
DOWNLOADS_DIR = PROJECT_DIR / "app" / "static" / "downloads"
LATEST_ALIAS = "android-control-helper-latest.apk"
METADATA_NAME = "helper-release.json"


def _git_build_ref() -> str:
    try:
        sha_result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        build_ref = sha_result.stdout.strip()
        dirty_result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        )
        if dirty_result.stdout.strip():
            return f"{build_ref}-dirty"
        return build_ref
    except Exception:
        return "nogit"


def _load_output_metadata() -> dict:
    metadata_path = OUTPUT_DIR / "output-metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Missing {metadata_path}. Build the helper first with ./gradlew assembleDebug"
        )
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    elements = data.get("elements") or []
    if not elements:
        raise RuntimeError(f"No APK elements found in {metadata_path}")
    return elements[0]


def _resolve_source_apk(element: dict) -> Path:
    output_file = element.get("outputFile")
    if output_file:
        candidate = OUTPUT_DIR / output_file
        if candidate.exists():
            return candidate

    apks = sorted(OUTPUT_DIR.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not apks:
        raise FileNotFoundError(f"No APK files found in {OUTPUT_DIR}")
    return apks[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    element = _load_output_metadata()
    source_apk = _resolve_source_apk(element)

    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    artifact_name = source_apk.name
    artifact_path = DOWNLOADS_DIR / artifact_name
    latest_path = DOWNLOADS_DIR / LATEST_ALIAS

    shutil.copy2(source_apk, artifact_path)
    shutil.copy2(source_apk, latest_path)

    stat = source_apk.stat()
    metadata = {
        "release_name": "android-control-helper",
        "artifact_name": artifact_name,
        "latest_alias": LATEST_ALIAS,
        "version_name": element.get("versionName", ""),
        "version_code": element.get("versionCode", 0),
        "build_sha": _git_build_ref(),
        "build_time_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y%m%d-%H%M%S"),
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_size_bytes": stat.st_size,
        "sha256": _sha256(source_apk),
        "source_apk": str(source_apk),
    }
    (DOWNLOADS_DIR / METADATA_NAME).write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
