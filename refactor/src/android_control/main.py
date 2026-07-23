"""FastAPI composition root."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import build_router
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

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        repository.initialize()
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

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    def root() -> RedirectResponse:
        return RedirectResponse("/dashboard")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    return app


app = create_app()
