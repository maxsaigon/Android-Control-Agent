"""FastAPI composition root."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .api import build_router
from .auth import AuthMiddleware, build_auth_router, hash_password
from .config import Settings, get_settings
from .database import Repository
from .hub import DeviceHub
from .media import MediaService
from .transports.registry import TransportRegistry
from .workflows.engine import WorkflowEngine


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or get_settings()
    repository = Repository(config.database_path)
    hub = DeviceHub(config.command_timeout_seconds)
    transports = TransportRegistry(config, hub)
    workflows = WorkflowEngine(repository, transports)
    media = MediaService(repository, config.data_dir / "media")
    session_secret = config.read_secret(config.session_secret_file, "Session secret")
    admin_password = config.read_secret(config.admin_password_file, "Admin password")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
        if repository.get_admin_password_hash(config.admin_username) is None:
            repository.ensure_admin(config.admin_username, hash_password(admin_password))
        yield

    app = FastAPI(
        title="Android Device Media Control",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
    )
    app.state.repository = repository
    app.state.hub = hub
    app.state.workflows = workflows
    app.include_router(build_auth_router(repository))
    app.include_router(
        build_router(
            repository,
            hub,
            transports,
            workflows,
            media,
            config.public_url.rstrip("/"),
        )
    )
    app.add_middleware(AuthMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="control_session",
        max_age=config.session_max_age_seconds,
        same_site="lax",
        https_only=config.cookie_secure,
    )

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/login", include_in_schema=False)
    def login_page() -> FileResponse:
        return FileResponse(static_dir / "login.html")

    return app
