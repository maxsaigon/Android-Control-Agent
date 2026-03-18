# 🤖 Android Control System

AI-powered Android device automation using DroidRun + GPT-4o + FastAPI.

Control multiple Android devices via natural language commands with hybrid automation:
- **Script Mode** ($0) — Hard-coded scripts for simple tasks (TikTok, YouTube, Facebook, Instagram)  
- **AI Mode** ($0.01+) — GPT-4o agent for complex, visual decision-making tasks
- **Scheduler** — Auto-run tasks with random timing to avoid detection

## Quick Start

### Option 1: Docker (Recommended)

```bash
# Clone
git clone https://github.com/maxsaigon/Android-Control-Agent.git
cd Android-Control-Agent

# Configure
cp .env.example .env
nano .env  # Add your OPENAI_API_KEY

# Run
docker compose up -d --build

# Open dashboard
open http://localhost:8000
```

### Option 2: Ubuntu Server (One-Command Deploy)

```bash
curl -fsSL https://raw.githubusercontent.com/maxsaigon/Android-Control-Agent/main/deploy.sh | bash
```

Or step by step:
```bash
git clone https://github.com/maxsaigon/Android-Control-Agent.git /opt/android-control
cd /opt/android-control
bash deploy.sh
```

### Option 3: Local Development

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install "droidrun[openai]" "fastapi[standard]" sqlmodel python-dotenv pydantic-settings
cp .env.example .env
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Connect Android Devices

1. Enable **Developer Options** → **USB Debugging** → **ADB over WiFi** on device
2. Connect via ADB:
   ```bash
   adb connect 192.168.1.xxx:5555
   ```
3. Add device in Dashboard → Devices panel

## Features

| Feature | Description |
|---------|-------------|
| 📱 Multi-Device | Control multiple Android devices simultaneously |
| 🔧 Script Mode | $0 cost — deterministic automation scripts |
| 🧠 AI Mode | GPT-4o agent with vision for complex tasks |
| ⏰ Scheduler | Auto-run tasks with anti-detection random timing |
| 📊 Dashboard | Real-time monitoring, task history, cost tracking |
| 🔄 Auto-Retry | Automatic retry on transient errors |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | OpenAI API key for AI mode |
| `LLM_BASE_URL` | ❌ | Custom LLM endpoint (OpenRouter, etc.) |
| `LLM_MODEL` | ❌ | Custom model name |

## Project Structure

```
├── app/
│   ├── main.py              # FastAPI entry point
│   ├── models.py             # SQLModel: Device, Task, Schedule
│   ├── database.py           # SQLite + SQLModel engine
│   ├── services/
│   │   ├── task_engine.py    # Task routing (script/AI)
│   │   ├── task_queue.py     # Background task queue
│   │   ├── script_runner.py  # Hard-coded automation scripts
│   │   ├── scheduler.py      # Background task scheduler
│   │   └── connection_watchdog.py
│   ├── routers/
│   │   ├── devices.py        # Device CRUD API
│   │   ├── tasks.py          # Task submit/status API
│   │   ├── schedules.py      # Schedule CRUD API
│   │   └── ws.py             # WebSocket live updates
│   ├── static/               # Dashboard (HTML/CSS/JS)
│   └── templates/            # Task templates (markdown)
├── Dockerfile
├── docker-compose.yml
├── deploy.sh                 # One-command server setup
├── pyproject.toml
└── config.yaml               # LLM configuration
```

## License

MIT
