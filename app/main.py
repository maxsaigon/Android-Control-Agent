"""FastAPI application entry point for Android Control System."""

import hashlib
import logging
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import create_db_and_tables, migrate_db, get_session
from app.models import Device, DeviceStatus, User
from app.routers import devices, tasks, ws, schedules, device_ws
from app.routers.auth import router as auth_router
from app.routers.videos import router as videos_router, account_router as accounts_router
from app.middleware.auth_middleware import AuthMiddleware
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
    # Startup: create database tables, then apply additive column migrations
    create_db_and_tables()
    migrate_db()

    # Ensure default admin user exists
    from sqlmodel import select
    session = next(get_session())
    try:
        existing_user = session.exec(
            select(User).where(User.username == "admin")
        ).first()
        if not existing_user:
            session.add(User(username="admin", password="admin"))
            session.commit()
            logging.info("👤 Created default admin user (admin/admin)")
    finally:
        session.close()
    
    # Register all existing devices with watchdog
    from sqlmodel import select as _sel
    session = next(get_session())
    try:
        devices_list = session.exec(
            _sel(Device).where(Device.status != DeviceStatus.OFFLINE)
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
    # Disable /docs in cloud — require auth via middleware instead
    docs_url="/docs",
    redoc_url=None,
)

# NOTE: Starlette applies middleware in REVERSE order of add_middleware() calls.
# The LAST middleware added wraps the OUTERMOST layer (runs first).
# Correct execution order: CORS → Session → Auth → Route handlers
#
# Therefore we add them in reverse order:

# 3. CORS (added last = outermost = runs first)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Auth middleware (runs after Session, so request.session is available)
app.add_middleware(AuthMiddleware)

# 1. Session middleware (added first = innermost = runs last before route)
#    But since Auth needs session, Session must actually run BEFORE Auth.
#    In Starlette's reverse model: add SessionMiddleware AFTER AuthMiddleware.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="acs_session",
    max_age=settings.session_expire_hours * 3600,
    https_only=False,  # Set True if HTTPS-only
    same_site="lax",
)

# Register routers
app.include_router(auth_router)               # Auth: login/logout/me
app.include_router(devices.router)
app.include_router(tasks.router)
app.include_router(ws.router)
app.include_router(schedules.router)
app.include_router(device_ws.router)         # Cloud device WebSocket
app.include_router(device_ws.token_router)    # Device token management
app.include_router(device_ws.register_router) # Device registration (login-based)
app.include_router(videos_router)             # Video management
app.include_router(accounts_router)           # Device-account mappings

# Serve static files (dashboard)
import pathlib
_static_dir = pathlib.Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")
app.mount("/debug-media", StaticFiles(directory=settings.screenshots_dir), name="debug-media")


@lru_cache(maxsize=1)
def _static_asset_version() -> str:
    """Build a cache-busting token from the current dashboard asset contents."""
    digest = hashlib.sha256()
    for path in (_static_dir / "style.css", _static_dir / "app.js"):
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


@lru_cache(maxsize=1)
def _render_dashboard_html() -> str:
    """Render dashboard HTML with fresh asset version query params."""
    html = (_static_dir / "index.html").read_text(encoding="utf-8")
    return html.replace("__STATIC_VERSION__", _static_asset_version())


@app.get("/login")
def login_page():
    """Serve the login page."""
    return FileResponse(str(_static_dir / "login.html"))


@app.get("/dashboard")
def dashboard():
    """Serve the web dashboard (requires auth)."""
    return HTMLResponse(_render_dashboard_html())

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


def _build_dashboard_overview():
    """Assemble dashboard snapshot and template-centric overview data."""
    from datetime import datetime, timedelta, timezone

    from sqlmodel import select

    from app.models import Task, TaskStatus as TS
    from app.services.task_queue import task_queue
    from app.services.template_manager import template_manager

    session = next(get_session())
    try:
        all_devices = session.exec(select(Device)).all()
        all_tasks = session.exec(select(Task)).all()

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        recent_window = now - timedelta(hours=24)

        tasks_today = [t for t in all_tasks if t.created_at and t.created_at >= today_start]
        recent_tasks = [t for t in all_tasks if t.created_at and t.created_at >= recent_window]
        running_tasks = [
            t for t in all_tasks if t.status in (TS.RUNNING, TS.PENDING)
        ]
        finished_tasks = [
            t for t in all_tasks if t.status in (TS.COMPLETED, TS.FAILED)
        ]
        recent_finished = [
            t for t in recent_tasks if t.status in (TS.COMPLETED, TS.FAILED)
        ]

        device_online = sum(1 for d in all_devices if d.status == DeviceStatus.ONLINE)
        device_busy = sum(1 for d in all_devices if d.status == DeviceStatus.BUSY)
        device_offline = sum(1 for d in all_devices if d.status == DeviceStatus.OFFLINE)

        tasks_completed = sum(1 for t in tasks_today if t.status == TS.COMPLETED)
        tasks_failed = sum(1 for t in tasks_today if t.status == TS.FAILED)
        tasks_running = sum(
            1 for t in tasks_today if t.status in (TS.RUNNING, TS.PENDING)
        )

        finished_total = len(finished_tasks)
        finished_success = sum(1 for t in finished_tasks if t.status == TS.COMPLETED)
        success_rate = (
            round(finished_success / finished_total * 100)
            if finished_total > 0
            else 100
        )

        recent_finished_total = len(recent_finished)
        recent_success_rate = (
            round(
                sum(1 for t in recent_finished if t.status == TS.COMPLETED)
                / recent_finished_total
                * 100
            )
            if recent_finished_total > 0
            else 100
        )

        TOKENS_PER_STEP = 680
        OUTPUT_PER_STEP = 20
        INPUT_COST_PER_M = 2.50
        OUTPUT_COST_PER_M = 10.00
        ai_tasks = [t for t in all_tasks if t.execution_mode != "script"]
        total_cost = sum(
            (t.steps_taken * TOKENS_PER_STEP / 1_000_000) * INPUT_COST_PER_M
            + (t.steps_taken * OUTPUT_PER_STEP / 1_000_000) * OUTPUT_COST_PER_M
            for t in ai_tasks
        )

        template_catalog = template_manager.list_templates()
        running_by_template: dict[str, int] = {}
        running_by_mode: dict[str, int] = {}
        for task in running_tasks:
            if task.template:
                running_by_template[task.template] = running_by_template.get(task.template, 0) + 1
            running_by_mode[task.execution_mode] = running_by_mode.get(task.execution_mode, 0) + 1

        top_templates = []
        for template in template_catalog:
            related = [t for t in all_tasks if t.template == template["name"]]
            recent_related = [t for t in recent_tasks if t.template == template["name"]]
            top_templates.append({
                **template,
                "running_count": sum(
                    1 for t in related if t.status in (TS.RUNNING, TS.PENDING)
                ),
                "recent_runs": len(recent_related),
                "recent_failures": sum(
                    1 for t in recent_related if t.status == TS.FAILED
                ),
                "last_used_at": max(
                    (t.created_at.isoformat() for t in related if t.created_at),
                    default=None,
                ),
            })

        queue_status = task_queue.status
        primary_template = next(
            (t for t in top_templates if t["is_primary"]),
            top_templates[0] if top_templates else None,
        )

        return {
            "snapshot": {
                "devices": {
                    "total": len(all_devices),
                    "online": device_online,
                    "busy": device_busy,
                    "offline": device_offline,
                },
                "tasks_today": {
                    "total": len(tasks_today),
                    "completed": tasks_completed,
                    "failed": tasks_failed,
                    "running": tasks_running,
                },
                "ai": {
                    "total_cost": round(total_cost, 4),
                    "success_rate": success_rate,
                    "recent_success_rate": recent_success_rate,
                },
                "queue": queue_status,
                "recent_failures_24h": sum(
                    1 for t in recent_tasks if t.status == TS.FAILED
                ),
                "active_comment_sessions": running_by_template.get("tiktok_comment", 0),
            },
            "running": {
                "total": len(running_tasks),
                "by_template": running_by_template,
                "by_mode": running_by_mode,
            },
            "primary_template": primary_template,
            "top_templates": top_templates,
        }
    finally:
        session.close()


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


@app.get("/api/dashboard/overview")
def dashboard_overview():
    """Rich dashboard snapshot for the TikTok-first dashboard tab."""
    return _build_dashboard_overview()


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


# --- APK Download & Device Setup ---

@app.get("/download/helper.apk")
def download_apk():
    """Download the latest AC Helper APK."""
    import os
    # Try multiple locations
    paths = [
        str(_static_dir / "downloads" / "ac-helper.apk"),
        str(pathlib.Path("/app/static/downloads/ac-helper.apk")),  # Docker
        str(pathlib.Path(__file__).parent.parent / "android-helper" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"),  # Local dev
    ]
    for p in paths:
        if os.path.exists(p):
            return FileResponse(
                p,
                media_type="application/vnd.android.package-archive",
                filename="ac-helper.apk",
            )
    from fastapi import HTTPException
    raise HTTPException(404, "APK not found. Build it first: cd android-helper && ./gradlew assembleDebug")


@app.get("/set")
def setup_page():
    """Device onboarding page — download APK + setup instructions."""
    from fastapi.responses import HTMLResponse
    from app.services.device_hub import device_hub

    hub = device_hub.status
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AC Helper — Device Setup</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
            color: #e0e0e0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            padding: 40px 20px;
        }}
        .container {{
            max-width: 480px;
            width: 100%;
        }}
        .logo {{
            text-align: center;
            margin-bottom: 32px;
        }}
        .logo h1 {{
            font-size: 28px;
            color: #fff;
            margin-bottom: 8px;
        }}
        .logo p {{
            color: #888;
            font-size: 14px;
        }}
        .card {{
            background: rgba(255,255,255,0.05);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 16px;
            padding: 24px;
            margin-bottom: 20px;
            backdrop-filter: blur(10px);
        }}
        .download-btn {{
            display: block;
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, #e94560, #c62a71);
            color: white;
            text-align: center;
            text-decoration: none;
            border-radius: 12px;
            font-size: 18px;
            font-weight: 600;
            transition: transform 0.2s;
        }}
        .download-btn:hover {{ transform: scale(1.02); }}
        .step {{
            display: flex;
            gap: 16px;
            padding: 12px 0;
            border-bottom: 1px solid rgba(255,255,255,0.05);
        }}
        .step:last-child {{ border-bottom: none; }}
        .step-num {{
            width: 32px;
            height: 32px;
            background: #e94560;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            flex-shrink: 0;
        }}
        .step-text h3 {{ font-size: 15px; color: #fff; margin-bottom: 4px; }}
        .step-text p {{ font-size: 13px; color: #999; }}
        .status {{
            text-align: center;
            padding: 12px;
            background: rgba(0,255,136,0.1);
            border-radius: 8px;
            font-size: 13px;
            color: #00ff88;
        }}
        code {{
            background: rgba(255,255,255,0.1);
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 13px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="logo">
            <h1>📱 AC Helper Setup</h1>
            <p>Android Control — Device Onboarding</p>
        </div>

        <div class="card">
            <a href="/download/helper.apk" class="download-btn">
                ⬇️ Download AC Helper APK
            </a>
        </div>

        <div class="card">
            <h2 style="margin-bottom:16px; font-size:18px;">Setup Steps</h2>
            <div class="step">
                <div class="step-num">1</div>
                <div class="step-text">
                    <h3>Download & Install APK</h3>
                    <p>Tap the button above on your Android device. Allow install from unknown sources if prompted.</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">2</div>
                <div class="step-text">
                    <h3>Enable Accessibility Service</h3>
                    <p>Open AC Helper → tap "Accessibility Settings" → enable "AC Helper".</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">3</div>
                <div class="step-text">
                    <h3>Switch to Cloud Mode</h3>
                    <p>In AC Helper, select ☁️ Cloud mode.</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">4</div>
                <div class="step-text">
                    <h3>Enter Login Info</h3>
                    <p>Server: <code>m.buonme.com</code><br>
                    Username: your login username<br>
                    Device Name: choose a name for this device</p>
                </div>
            </div>
            <div class="step">
                <div class="step-num">5</div>
                <div class="step-text">
                    <h3>Tap Connect</h3>
                    <p>Tap "Save & Connect". The notification should show "Connected ✅".<br>
                    Device sẽ tự động được thêm vào dashboard.</p>
                </div>
            </div>
        </div>

        <div class="status">
            🟢 Hub Status: {hub['connected_devices']} device(s) connected
        </div>
    </div>
</body>
</html>"""
    return HTMLResponse(html)
