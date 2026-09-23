#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HELPER_DIR="$ROOT_DIR/android-helper"

cd "$HELPER_DIR"
./gradlew assembleRelease
python3 "$HELPER_DIR/publish_helper_release.py"
