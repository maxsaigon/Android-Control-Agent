#!/usr/bin/env python3
"""Publish the latest helper APK into app/static/downloads/ with metadata."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
import zipfile

PROJECT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_DIR / "android-helper" / "app" / "build" / "outputs" / "apk" / "release"
DOWNLOADS_DIR = PROJECT_DIR / "app" / "static" / "downloads"
LATEST_ALIAS = "android-control-helper-latest.apk"
METADATA_NAME = "helper-release.json"


def _load_output_metadata() -> dict:
    metadata_path = OUTPUT_DIR / "output-metadata.json"
    if not metadata_path.exists():
        raise FileNotFoundError(
            f"Missing {metadata_path}. Build the helper first with ./gradlew assembleRelease"
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

    raise FileNotFoundError(f"Missing APK referenced by Gradle metadata: {output_file}")


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
    with zipfile.ZipFile(source_apk) as archive:
        build = json.loads(archive.read("assets/helper-build.json"))
    version_name = build["version_name"]
    version_code = int(build["version_code"])
    if version_code != element["versionCode"] or version_name != element["versionName"]:
        raise ValueError("APK build metadata disagrees with Gradle output")
    digest = _sha256(source_apk)
    previous_path = DOWNLOADS_DIR / METADATA_NAME
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        if version_code < previous["version_code"]:
            raise ValueError("Release versionCode must increase")
        if version_code == previous["version_code"] and digest != previous["sha256"]:
            raise ValueError("Changed APK must use a new versionCode")
    build_sha = build["build_sha"]
    build_time_utc = build["build_time_utc"]
    # Unique artifact for every publish to avoid CDN/browser stale cache on same filename.
    artifact_name = (
        f"android-control-helper-v{version_name}+{version_code}"
        f"-{build_time_utc}-{build_sha}.apk"
    )
    artifact_path = DOWNLOADS_DIR / artifact_name
    latest_path = DOWNLOADS_DIR / LATEST_ALIAS

    if artifact_path.exists() and _sha256(artifact_path) != digest:
        raise ValueError("Refusing to overwrite an immutable release artifact")
    for destination in (artifact_path, latest_path):
        temporary = destination.with_suffix(".apk.tmp")
        shutil.copy2(source_apk, temporary)
        temporary.replace(destination)

    stat = source_apk.stat()
    metadata = {
        "release_name": "android-control-helper",
        "artifact_name": artifact_name,
        "latest_alias": LATEST_ALIAS,
        "version_name": version_name,
        "version_code": version_code,
        "build_sha": build_sha,
        "build_time_utc": build_time_utc,
        "published_at_utc": datetime.now(timezone.utc).isoformat(),
        "file_size_bytes": stat.st_size,
        "sha256": digest,
        "package_name": build["package_name"],
        "min_sdk": build["min_sdk"],
        "protocol_version": build["protocol_version"],
    }
    metadata_temp = DOWNLOADS_DIR / (METADATA_NAME + ".tmp")
    metadata_temp.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    metadata_temp.replace(DOWNLOADS_DIR / METADATA_NAME)

    print(json.dumps(metadata, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
