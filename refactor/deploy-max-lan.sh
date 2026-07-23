#!/usr/bin/env bash
# Deploy the refactor beside the legacy service. The public tunnel is untouched.

set -euo pipefail

SERVER="${SERVER:-max@max.lan}"
REMOTE_ROOT="${REMOTE_ROOT:-/home/max/android-control}"
REMOTE_REFACTOR="$REMOTE_ROOT/refactor"
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOCAL_REFACTOR="$PROJECT_ROOT/refactor"

cd "$PROJECT_ROOT"

BRANCH="$(git branch --show-current)"
HEAD_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git ls-remote --heads origin "refs/heads/$BRANCH" | awk '{print $1}')"

if [[ -z "$BRANCH" || -z "$REMOTE_SHA" || "$HEAD_SHA" != "$REMOTE_SHA" ]]; then
  echo "Current HEAD must be pushed to origin/$BRANCH before deployment."
  echo "Local:  $HEAD_SHA"
  echo "Remote: ${REMOTE_SHA:-missing}"
  exit 1
fi

echo "Deploying refactor $HEAD_SHA to $SERVER:$REMOTE_REFACTOR"

ssh "$SERVER" "set -e
  mkdir -p '$REMOTE_REFACTOR/runtime/backups'
  if [ -f '$REMOTE_REFACTOR/runtime/control.db' ]; then
    timestamp=\$(date +%Y%m%d-%H%M%S)
    cp '$REMOTE_REFACTOR/runtime/control.db' \
      '$REMOTE_REFACTOR/runtime/backups/control.db.pre_deploy_'\$timestamp
  fi
  test -f '$REMOTE_ROOT/.env'"

rsync -az --delete \
  --exclude '.env' \
  --exclude '.pytest_cache' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'runtime' \
  "$LOCAL_REFACTOR/" "$SERVER:$REMOTE_REFACTOR/"

ssh "$SERVER" "set -e
  cd '$REMOTE_ROOT'
  docker compose -f refactor/docker-compose.yml up -d --build
  for attempt in 1 2 3 4 5 6; do
    if curl -sf http://localhost:8090/api/health >/tmp/refactor-health.json; then
      break
    fi
    sleep 3
  done
  curl -sf http://localhost:8090/api/health
  curl -sf http://localhost:8090/api/resources
  curl -sf http://localhost:8090/dashboard >/dev/null
  docker inspect --format='{{.State.Health.Status}}' android-control-refactor"

echo
echo "Refactor deployed at http://max.lan:8090"
echo "Public Cloudflare route remains on the legacy service."
