#!/bin/bash
# Deploy Android Control to cloud server
# Usage: ./deploy/cloud-setup.sh [tunnel-token]
#
# Prerequisites:
#   - SSH access to max@max.local (password: in your env)
#   - Docker + Docker Compose on server
#   - Cloudflare Tunnel token from Zero Trust dashboard

set -e

SERVER="max@max.local"
REMOTE_DIR="/home/max/android-control"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "📦 Deploying Android Control to $SERVER..."

# 1. Sync code to server (exclude unnecessary files)
echo "📤 Syncing code..."
rsync -avz --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'venv' \
    --exclude 'node_modules' \
    --exclude '.agents' \
    --exclude 'screenshots' \
    --exclude 'android-helper/build' \
    --exclude 'android-helper/.gradle' \
    --exclude 'android-helper/app/build/intermediates' \
    --exclude 'android-helper/app/build/tmp' \
    --exclude '*.egg-info' \
    "$PROJECT_DIR/" "$SERVER:$REMOTE_DIR/"

# 2. Create .env with tunnel token if provided
if [ -n "$1" ]; then
    echo "🔑 Setting Cloudflare Tunnel token..."
    ssh "$SERVER" "echo 'CLOUDFLARE_TUNNEL_TOKEN=$1' > $REMOTE_DIR/.env"
fi

# 3. Build and start
echo "🐳 Building and starting containers..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose -f docker-compose.cloud.yml up -d --build"

# 4. Wait for health
echo "⏳ Waiting for health check..."
sleep 5
ssh "$SERVER" "curl -sf http://localhost:8080/api/health | python3 -m json.tool" && \
    echo "✅ Server is healthy!" || \
    echo "⚠️ Health check failed — check logs: ssh $SERVER 'cd $REMOTE_DIR && docker compose -f docker-compose.cloud.yml logs'"

echo ""
echo "🎉 Deployment complete!"
echo "   Local: http://max.local:8080"
echo "   Cloud: https://m.buonme.com (after Cloudflare Tunnel setup)"
echo ""
echo "📋 Useful commands:"
echo "   Logs:    ssh $SERVER 'cd $REMOTE_DIR && docker compose -f docker-compose.cloud.yml logs -f'"
echo "   Restart: ssh $SERVER 'cd $REMOTE_DIR && docker compose -f docker-compose.cloud.yml restart'"
echo "   Stop:    ssh $SERVER 'cd $REMOTE_DIR && docker compose -f docker-compose.cloud.yml down'"
