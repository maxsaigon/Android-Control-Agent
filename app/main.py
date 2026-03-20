"""FastAPI application entry point for Android Control System."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.database import create_db_and_tables, get_session
from app.models import Device, DeviceStatus
from app.routers import devices, tasks, ws, schedules, device_ws
from app.services.connection_watchdog import watchdog
from app.services.scheduler import scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    # Startup: create database tables
    create_db_and_tables()
    
    # Register all existing devices with watchdog
    from sqlmodel import select
    session = next(get_session())
    try:
        devices_list = session.exec(
            select(Device).where(Device.status != DeviceStatus.OFFLINE)
        ).all()
        for dev in devices_list:
            watchdog.register_device(dev.ip_address, dev.adb_port)
    finally:
        session.close()
    
    # Clean up orphaned tasks from previous server runs
    from app.services.task_queue import task_queue
    cleaned = task_queue.cleanup_orphaned()
    if cleaned:
        logging.info(f"🧹 Cleaned {cleaned} orphaned task(s) from previous run")

    # Start connection watchdog
    watchdog.start()
    
    # Start task scheduler
    await scheduler.start()
    
    logging.info("🚀 Android Control System started")
    logging.info("📖 API docs: http://localhost:8000/docs")
    yield
    # Shutdown
    await scheduler.stop()
    watchdog.stop()
    logging.info("👋 Android Control System stopped")


app = FastAPI(
    title="Android Control System",
    description=(
        "AI-powered Android device automation using DroidRun + GPT-4o. "
        "Control multiple Android devices via natural language commands."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(devices.router)
app.include_router(tasks.router)
app.include_router(ws.router)
app.include_router(schedules.router)
app.include_router(device_ws.router)         # Cloud device WebSocket
app.include_router(device_ws.token_router)    # Device token management

# Serve static files (dashboard)
import pathlib
_static_dir = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/dashboard")
def dashboard():
    """Serve the web dashboard."""
    return FileResponse(str(_static_dir / "index.html"))

@app.get("/")
def root():
    """Health check endpoint."""
    return {
        "name": "Android Control System",
        "version": "0.2.0",
        "status": "running",
        "docs": "/docs",
    }


@app.get("/api/templates")
def list_templates():
    """List available task templates."""
    from app.services.template_manager import template_manager
    return template_manager.list_templates()


@app.get("/api/health")
def health():
    """Detailed health check with watchdog and device hub status."""
    from app.services.device_hub import device_hub
    return {
        "status": "healthy",
        "services": {
            "database": "ok",
            "ai_agent": "available",
        },
        "watchdog": watchdog.status,
        "device_hub": device_hub.status,
    }


@app.get("/api/stats")
def dashboard_stats():
    """Aggregate stats for dashboard overview cards."""
    from datetime import datetime, timezone, timedelta
    from sqlmodel import select, func

    session = next(get_session())
    try:
        # Device counts
        all_devices = session.exec(select(Device)).all()
        device_online = sum(1 for d in all_devices if d.status == DeviceStatus.ONLINE)
        device_busy = sum(1 for d in all_devices if d.status == DeviceStatus.BUSY)
        device_offline = sum(1 for d in all_devices if d.status == DeviceStatus.OFFLINE)

        # Task counts today
        from app.models import Task, TaskStatus as TS
        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        all_tasks_today = session.exec(
            select(Task).where(Task.created_at >= today_start)
        ).all()

        tasks_completed = sum(1 for t in all_tasks_today if t.status == TS.COMPLETED)
        tasks_failed = sum(1 for t in all_tasks_today if t.status == TS.FAILED)
        tasks_running = sum(
            1 for t in all_tasks_today
            if t.status in (TS.RUNNING, TS.PENDING)
        )
        tasks_total = len(all_tasks_today)

        # Success rate (all time, excluding pending/running/cancelled)
        all_finished = session.exec(
            select(Task).where(
                Task.status.in_([TS.COMPLETED, TS.FAILED])  # type: ignore
            )
        ).all()
        finished_total = len(all_finished)
        finished_success = sum(1 for t in all_finished if t.status == TS.COMPLETED)
        success_rate = (
            round(finished_success / finished_total * 100)
            if finished_total > 0
            else 100
        )

        # Total AI cost (all time)
        TOKENS_PER_STEP = 680
        OUTPUT_PER_STEP = 20
        INPUT_COST_PER_M = 2.50
        OUTPUT_COST_PER_M = 10.00
        ai_tasks = session.exec(
            select(Task).where(Task.execution_mode != "script")
        ).all()
        total_cost = sum(
            (t.steps_taken * TOKENS_PER_STEP / 1_000_000) * INPUT_COST_PER_M
            + (t.steps_taken * OUTPUT_PER_STEP / 1_000_000) * OUTPUT_COST_PER_M
            for t in ai_tasks
        )

        return {
            "devices": {
                "total": len(all_devices),
                "online": device_online,
                "busy": device_busy,
                "offline": device_offline,
            },
            "tasks_today": {
                "total": tasks_total,
                "completed": tasks_completed,
                "failed": tasks_failed,
                "running": tasks_running,
            },
            "success_rate": success_rate,
            "total_cost": round(total_cost, 4),
        }
    finally:
        session.close()
