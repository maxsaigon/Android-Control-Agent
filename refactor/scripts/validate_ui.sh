#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HTML="$ROOT/src/android_control/static/index.html"
CSS="$ROOT/src/android_control/static/style.css"
JS="$ROOT/src/android_control/static/app.js"

errors=0

duplicates="$(grep -oE 'id="[^"]+"' "$HTML" | sort | uniq -d || true)"
if [[ -n "$duplicates" ]]; then
  echo "Duplicate IDs:"
  echo "$duplicates"
  errors=$((errors + 1))
fi

js_ids="$(grep -oE '\$\("[A-Za-z0-9_-]+"\)' "$JS" | cut -d '"' -f 2 | sort -u || true)"
for id in $js_ids; do
  if ! grep -q "id=\"$id\"" "$HTML"; then
    echo "Missing HTML id referenced by JS: $id"
    errors=$((errors + 1))
  fi
done

if grep -nE '(<button[^>]*>[^<]*[😀-🙏]|onclick=)' "$HTML"; then
  echo "Inline handlers or emoji button icons are not allowed"
  errors=$((errors + 1))
fi

grep -q 'prefers-reduced-motion' "$CSS" || {
  echo "Missing reduced-motion handling"
  errors=$((errors + 1))
}
grep -q 'focus-visible' "$CSS" || {
  echo "Missing visible focus handling"
  errors=$((errors + 1))
}

if [[ $errors -eq 0 ]]; then
  echo "Refactor UI validation passed"
fi
exit "$errors"
