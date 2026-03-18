#!/usr/bin/env bash
# =============================================================================
# UI Validation Script for Android Control Dashboard
# Checks HTML/CSS/JS consistency (macOS & Linux compatible)
# Usage: bash .agents/skills/ui-dashboard/scripts/validate_ui.sh
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

ERRORS=0
WARNINGS=0

DIR="$(cd "$(dirname "$0")/../../../.." && pwd)"
HTML="$DIR/app/static/index.html"
CSS="$DIR/app/static/style.css"
JS="$DIR/app/static/app.js"

echo "═══════════════════════════════════════════"
echo " UI Validation — Android Control Dashboard"
echo "═══════════════════════════════════════════"
echo ""

# --- Check files exist ---
echo "📁 Checking files..."
for f in "$HTML" "$CSS" "$JS"; do
    if [[ -f "$f" ]]; then
        echo -e "  ${GREEN}✓${NC} $(basename "$f")"
    else
        echo -e "  ${RED}✗${NC} Missing: $f"
        ((ERRORS++))
    fi
done
echo ""

# --- Check for duplicate IDs in HTML ---
echo "🔍 Checking for duplicate HTML IDs..."
duplicate_ids=$(grep -oE 'id="[^"]*"' "$HTML" 2>/dev/null | sort | uniq -d || true)
if [[ -z "$duplicate_ids" ]]; then
    echo -e "  ${GREEN}✓${NC} No duplicate IDs found"
else
    echo -e "  ${RED}✗${NC} Duplicate IDs found:"
    echo "$duplicate_ids" | while read -r line; do
        echo "    - $line"
    done
    ((ERRORS++))
fi
echo ""

# --- Check JS getElementById references exist in HTML ---
echo "🔍 Checking JS → HTML ID references..."
js_ids=$(grep -oE "getElementById\(['\"][^'\"]+['\"]\)" "$JS" 2>/dev/null \
    | sed -E "s/getElementById\(['\"]([^'\"]+)['\"]\)/\1/" | sort -u || true)
missing_ids=0
for id in $js_ids; do
    if ! grep -q "id=\"$id\"" "$HTML" 2>/dev/null; then
        echo -e "  ${RED}✗${NC} JS references id='$id' but not found in HTML"
        ((missing_ids++))
    fi
done
if [[ $missing_ids -eq 0 ]]; then
    echo -e "  ${GREEN}✓${NC} All JS getElementById references found in HTML ($( echo "$js_ids" | wc -w | tr -d ' ') IDs)"
else
    ((ERRORS += missing_ids))
fi
echo ""

# --- Check onclick handlers exist in JS ---
echo "🔍 Checking HTML onclick → JS function references..."
onclick_funcs=$(grep -oE 'onclick="[^"]*' "$HTML" 2>/dev/null \
    | sed -E 's/onclick="//; s/event\.stopPropagation\(\);\s*//' \
    | grep -oE '^[a-zA-Z_][a-zA-Z0-9_]*' | sort -u || true)
missing_funcs=0
for func in $onclick_funcs; do
    [[ "$func" == "event" ]] && continue
    if ! grep -qE "(async )?function $func" "$JS" 2>/dev/null; then
        echo -e "  ${RED}✗${NC} HTML onclick='$func()' but function not defined in JS"
        ((missing_funcs++))
    fi
done
if [[ $missing_funcs -eq 0 ]]; then
    echo -e "  ${GREEN}✓${NC} All onclick handlers found in JS ($( echo "$onclick_funcs" | wc -w | tr -d ' ') functions)"
else
    ((ERRORS += missing_funcs))
fi
echo ""

# --- Check onchange/onsubmit/oninput handlers ---
echo "🔍 Checking HTML event handlers → JS..."
event_funcs=$(grep -oE '(onchange|onsubmit|oninput)="[^"]*' "$HTML" 2>/dev/null \
    | sed -E 's/(onchange|onsubmit|oninput)="//' \
    | grep -oE '^[a-zA-Z_][a-zA-Z0-9_]*' | sort -u || true)
missing_events=0
for func in $event_funcs; do
    if ! grep -qE "(async )?function $func" "$JS" 2>/dev/null; then
        echo -e "  ${RED}✗${NC} Event handler '$func()' not defined in JS"
        ((missing_events++))
    fi
done
if [[ $missing_events -eq 0 ]]; then
    echo -e "  ${GREEN}✓${NC} All event handlers found in JS ($( echo "$event_funcs" | wc -w | tr -d ' ') handlers)"
else
    ((ERRORS += missing_events))
fi
echo ""

# --- Check API endpoints in JS match known routes ---
echo "🔍 Checking API endpoints..."
known_endpoints=(
    "/api/devices"
    "/api/templates"
    "/api/tasks"
    "/api/tasks/batch"
    "/api/tasks/running"
    "/api/tasks/queue-status"
    "/api/health"
    "/api/stats"
)
api_calls=$(grep -oE 'fetch\(`\$\{API\}(/api/[a-z/_-]+)' "$JS" 2>/dev/null \
    | sed -E 's/fetch\(`\$\{API\}//' | sort -u || true)
unknown_apis=0
for api in $api_calls; do
    base_api=$(echo "$api" | sed -E 's|/\$\{[^}]+\}||g')
    matched=false
    for known in "${known_endpoints[@]}"; do
        if [[ "$base_api" == "$known"* ]]; then
            matched=true
            break
        fi
    done
    if ! $matched; then
        echo -e "  ${YELLOW}⚠${NC} Unknown API endpoint: $api"
        ((unknown_apis++))
        ((WARNINGS++))
    fi
done
if [[ $unknown_apis -eq 0 ]]; then
    echo -e "  ${GREEN}✓${NC} All API endpoints are known ($( echo "$api_calls" | wc -w | tr -d ' ') endpoints)"
fi
echo ""

# --- Check CSS variables are used (not hardcoded colors) ---
echo "🔍 Checking for hardcoded colors in CSS..."
hardcoded=$(grep -nE '#[0-9a-fA-F]{3,8}' "$CSS" 2>/dev/null \
    | grep -v ':root' | grep -v '^\s*/\*' | head -20 || true)
if [[ -z "$hardcoded" ]]; then
    echo -e "  ${GREEN}✓${NC} No hardcoded colors outside :root"
else
    count=$(echo "$hardcoded" | wc -l | tr -d ' ')
    echo -e "  ${YELLOW}⚠${NC} Found $count hex colors outside :root (may be intentional)"
    ((WARNINGS++))
fi
echo ""

# --- File sizes ---
echo "📊 File sizes:"
for f in "$HTML" "$CSS" "$JS"; do
    size=$(wc -l < "$f" | tr -d ' ')
    bytes=$(wc -c < "$f" | tr -d ' ')
    echo "  $(basename "$f"): ${size} lines, ${bytes} bytes"
done
echo ""

# --- Summary ---
echo "═══════════════════════════════════════════"
if [[ $ERRORS -eq 0 && $WARNINGS -eq 0 ]]; then
    echo -e "${GREEN}✅ All checks passed!${NC}"
elif [[ $ERRORS -eq 0 ]]; then
    echo -e "${YELLOW}⚠️  Passed with $WARNINGS warning(s)${NC}"
else
    echo -e "${RED}❌ Found $ERRORS error(s) and $WARNINGS warning(s)${NC}"
fi
echo "═══════════════════════════════════════════"

exit $ERRORS
