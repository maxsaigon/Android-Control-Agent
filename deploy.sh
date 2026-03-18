#!/bin/bash
# =============================================================
# Android Control System — Server Setup Script (Ubuntu)
# Usage: bash deploy.sh
# =============================================================

set -e

APP_DIR="/opt/android-control"
REPO_URL="https://github.com/maxsaigon/Android-Control-Agent.git"

echo "🤖 Android Control System — Server Deploy"
echo "=========================================="

# 1. Install Docker if not present
if ! command -v docker &>/dev/null; then
    echo "📦 Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    echo "✅ Docker installed. You may need to logout/login for group changes."
fi

# 2. Install Docker Compose plugin if needed
if ! docker compose version &>/dev/null; then
    echo "📦 Installing Docker Compose plugin..."
    sudo apt-get update && sudo apt-get install -y docker-compose-plugin
fi

# 3. Install ADB (for connecting to Android devices on LAN)
if ! command -v adb &>/dev/null; then
    echo "📦 Installing ADB..."
    sudo apt-get update && sudo apt-get install -y android-tools-adb
fi

# 4. Clone or update repo
if [ -d "$APP_DIR" ]; then
    echo "🔄 Updating existing installation..."
    cd "$APP_DIR"
    git pull origin main
else
    echo "📥 Cloning repository..."
    sudo mkdir -p "$APP_DIR"
    sudo chown "$USER:$USER" "$APP_DIR"
    git clone "$REPO_URL" "$APP_DIR"
    cd "$APP_DIR"
fi

# 5. Create .env if not exists
if [ ! -f ".env" ]; then
    echo "⚙️  Creating .env from template..."
    cp .env.example .env
    echo ""
    echo "⚠️  IMPORTANT: Edit .env with your API keys:"
    echo "   nano $APP_DIR/.env"
    echo ""
fi

# 6. Create data directories
mkdir -p data screenshots

# 7. Build and start
echo "🐳 Building Docker image..."
docker compose build

echo "🚀 Starting Android Control System..."
docker compose up -d

echo ""
echo "=========================================="
echo "✅ Android Control System is running!"
echo ""
echo "🌐 Dashboard:  http://$(hostname -I | awk '{print $1}'):8000"
echo "📖 API Docs:   http://$(hostname -I | awk '{print $1}'):8000/docs"
echo ""
echo "📋 Useful commands:"
echo "   docker compose logs -f        # View logs"
echo "   docker compose restart        # Restart"
echo "   docker compose down           # Stop"
echo "   docker compose up -d --build  # Rebuild & restart"
echo ""
echo "🔧 Don't forget to:"
echo "   1. Edit .env with your OPENAI_API_KEY"
echo "   2. Connect Android devices via ADB:"
echo "      adb connect <device-ip>:5555"
echo "=========================================="
