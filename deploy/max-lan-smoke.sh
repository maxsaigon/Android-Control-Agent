#!/bin/bash
# Deploy current repo state to max.lan and run authenticated smoke tests.
#
# Rule: current HEAD must already be pushed to origin before deploy.

set -euo pipefail

SERVER="${SERVER:-max@max.lan}"
REMOTE_DIR="${REMOTE_DIR:-/home/max/android-control}"
REMOTE_COMPOSE_FILE="${REMOTE_COMPOSE_FILE:-docker-compose.yml}"
REMOTE_DB_PATH="${REMOTE_DB_PATH:-$REMOTE_DIR/data/android_control.db}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://m.buonme.com}"
PUBLIC_SMOKE_OUT_DIR="${PUBLIC_SMOKE_OUT_DIR:-/tmp/android-control-public-smoke}"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

BRANCH="$(git branch --show-current)"
if [ -z "$BRANCH" ]; then
    echo "❌ Could not determine current git branch."
    exit 1
fi

HEAD_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git ls-remote --heads origin "refs/heads/$BRANCH" | awk '{print $1}')"

if [ -z "$REMOTE_SHA" ]; then
    echo "❌ Branch '$BRANCH' is not backed up on origin."
    echo "   Push first: git push -u origin $BRANCH"
    exit 1
fi

if [ "$HEAD_SHA" != "$REMOTE_SHA" ]; then
    echo "❌ Current HEAD is not backed up on origin/$BRANCH."
    echo "   Local:  $HEAD_SHA"
    echo "   Remote: $REMOTE_SHA"
    echo "   Push first, then deploy."
    exit 1
fi

echo "✅ Backup rule satisfied: origin/$BRANCH matches current HEAD."
echo "📦 Deploying $HEAD_SHA to $SERVER:$REMOTE_DIR"
echo "🧱 Remote compose: $REMOTE_COMPOSE_FILE"

rsync -avz --delete \
    --exclude '.git' \
    --exclude '.env' \
    --exclude '.DS_Store' \
    --exclude '.pytest_cache' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'venv' \
    --exclude 'node_modules' \
    --exclude '.agents' \
    --exclude 'data' \
    --exclude 'screenshots' \
    --exclude 'android-helper/build' \
    --exclude 'android-helper/.gradle' \
    --exclude 'android-helper/app/build' \
    --exclude '*.egg-info' \
    --include 'app/static/downloads/android-control-helper-latest.apk' \
    --exclude 'app/static/downloads/*.apk' \
    "$PROJECT_DIR/" "$SERVER:$REMOTE_DIR/"

ssh "$SERVER" "set -e; \
    cd $REMOTE_DIR && \
    mkdir -p data/backups && \
    if [ -f \"$REMOTE_DB_PATH\" ]; then \
        TS=\$(date +%Y%m%d-%H%M%S); \
        cp \"$REMOTE_DB_PATH\" \"data/backups/android_control.db.pre_deploy_\$TS\"; \
        echo \"🗄️ Backed up database to data/backups/android_control.db.pre_deploy_\$TS\"; \
    fi && \
    docker compose -f \"$REMOTE_COMPOSE_FILE\" up -d --build"

echo "⏳ Waiting for app to come back..."
sleep 6

ssh "$SERVER" "python3 - <<'PY'
import json
import subprocess
import tempfile
import urllib.request

base = 'http://localhost:8001'

def run(cmd):
    return subprocess.check_output(cmd, text=True).strip()

health = urllib.request.urlopen(f'{base}/api/health', timeout=10).read().decode()
print('HEALTH_OK', health)

cookie = tempfile.NamedTemporaryFile(delete=False)
cookie_path = cookie.name
cookie.close()

payload = json.dumps({'username': 'admin', 'password': 'admin'})
run([
    'curl', '-sf',
    '-c', cookie_path,
    '-H', 'Content-Type: application/json',
    '-d', payload,
    f'{base}/auth/login',
])

run(['curl', '-sf', '-b', cookie_path, f'{base}/auth/me'])
run(['curl', '-sf', '-b', cookie_path, f'{base}/dashboard'])

templates = json.loads(run(['curl', '-sf', '-b', cookie_path, f'{base}/api/templates']))
overview = json.loads(run(['curl', '-sf', '-b', cookie_path, f'{base}/api/dashboard/overview']))
devices = json.loads(run(['curl', '-sf', '-b', cookie_path, f'{base}/api/devices']))
running = json.loads(run(['curl', '-sf', '-b', cookie_path, f'{base}/api/tasks/running']))
helper_release = json.loads(run(['curl', '-sf', f'{base}/api/helper/release']))
helper_headers = run(['curl', '-s', '-D', '-', '-o', '/dev/null', f'{base}/download/helper.apk'])

assert any(t['name'] == 'tiktok_comment' and t['mode'] == 'hybrid' for t in templates)
assert overview['primary_template']['name'] == 'tiktok_comment'
assert helper_release['available'] is True
assert helper_release['metadata'].get('version_name')
assert 'android-control-helper' in helper_headers.lower()

print('AUTH_OK')
print('TEMPLATES_OK', len(templates))
print('OVERVIEW_OK', overview['snapshot']['active_comment_sessions'])
print('DEVICES_OK', len(devices))
print('RUNNING_OK', len(running))
print('HELPER_OK', helper_release['metadata'].get('version_name'))
PY"

echo "🌐 Running public-domain Playwright smoke on $PUBLIC_BASE_URL"
python3 "$PROJECT_DIR/deploy/public_domain_smoke.py" \
    --base-url "$PUBLIC_BASE_URL" \
    --username admin \
    --password admin \
    --out-dir "$PUBLIC_SMOKE_OUT_DIR"

echo "🎉 Deploy + smoke test complete."
