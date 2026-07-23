"""HTTP and WebSocket API for the refactored control plane."""

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile, WebSocket
from fastapi.responses import FileResponse

from .database import Repository
from .hub import DeviceHub
from .media import MediaService
from .models import (
    ActionRequest,
    ActionResult,
    DeviceCreate,
    DeviceStatus,
    DeviceView,
    MediaView,
    ProvisionedDevice,
    RunView,
    TransportKind,
    WorkflowStart,
)
from .transports.registry import TransportRegistry
from .workflows.engine import WorkflowEngine

ALLOWED_ACTIONS = {
    "tap",
    "swipe",
    "type_text",
    "global_action",
    "get_ui_tree",
    "screenshot",
    "get_foreground_app",
    "launch_app",
}


def build_router(
    repository: Repository,
    hub: DeviceHub,
    transports: TransportRegistry,
    workflows: WorkflowEngine,
    media: MediaService,
    public_url: str,
) -> APIRouter:
    router = APIRouter()

    def device_or_404(device_id: int) -> DeviceView:
        try:
            return repository.get_device(device_id)
        except KeyError as exc:
            raise HTTPException(404, "Device not found") from exc

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "product": "Android Device Media Control",
            "version": "0.1.0",
            "connected_devices": len(hub.connections),
        }

    @router.get("/api/resources")
    def resources() -> dict[str, Any]:
        return {
            "public_url": public_url,
            "cloud_websocket_path": "/ws/device/{token}",
            "secrets": {
                "openai": bool(os.getenv("OPENAI_API_KEY")),
                "deepseek": bool(os.getenv("DEEPSEEK_API_KEY")),
                "cloudflare_tunnel": bool(os.getenv("CLOUDFLARE_TUNNEL_TOKEN")),
            },
        }

    @router.get("/api/devices", response_model=list[DeviceView])
    def list_devices() -> list[DeviceView]:
        return repository.list_devices()

    @router.post("/api/devices", response_model=ProvisionedDevice, status_code=201)
    def create_device(data: DeviceCreate) -> ProvisionedDevice:
        device, token = repository.create_device(data)
        return ProvisionedDevice(
            device=device,
            token=token,
            websocket_url=f"{public_url.replace('https://', 'wss://').replace('http://', 'ws://')}"
            f"/ws/device/{token}"
            if token
            else None,
        )

    @router.post("/api/devices/{device_id}/actions/{action}", response_model=ActionResult)
    async def device_action(
        device_id: int,
        action: str,
        body: ActionRequest,
    ) -> ActionResult:
        if action not in ALLOWED_ACTIONS:
            raise HTTPException(400, "Unsupported action")
        device = device_or_404(device_id)
        try:
            result = await transports.for_device(device).command(action, body.params)
        except (ConnectionError, RuntimeError, ValueError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return ActionResult(action=action, result=result)

    @router.get("/api/workflows")
    def workflow_registry() -> list[dict[str, Any]]:
        return workflows.registry()

    @router.post("/api/devices/{device_id}/runs", response_model=RunView, status_code=202)
    def start_run(device_id: int, body: WorkflowStart) -> RunView:
        device_or_404(device_id)
        try:
            return workflows.start(device_id, body.workflow, body.params)
        except KeyError as exc:
            raise HTTPException(400, "Unknown workflow") from exc

    @router.get("/api/runs", response_model=list[RunView])
    def list_runs(limit: int = 30) -> list[RunView]:
        return [RunView(**run) for run in repository.list_runs(min(limit, 100))]

    @router.get("/api/runs/{run_id}", response_model=RunView)
    def get_run(run_id: str) -> RunView:
        try:
            return RunView(**repository.get_run(run_id))
        except KeyError as exc:
            raise HTTPException(404, "Run not found") from exc

    @router.post("/api/runs/{run_id}/cancel", status_code=202)
    def cancel_run(run_id: str) -> dict[str, bool]:
        try:
            workflows.cancel(run_id)
        except KeyError as exc:
            raise HTTPException(409, "Run is not active") from exc
        return {"accepted": True}

    @router.get("/api/media", response_model=list[MediaView])
    def list_media() -> list[MediaView]:
        return [MediaView(**item) for item in repository.list_media()]

    @router.post("/api/media", response_model=MediaView, status_code=201)
    async def upload_media(file: UploadFile = File(...)) -> MediaView:
        return await media.save(file)

    @router.post("/api/devices/{device_id}/media/{media_id}", response_model=ActionResult)
    async def push_media(device_id: int, media_id: str) -> ActionResult:
        device = device_or_404(device_id)
        if device.transport != TransportKind.ADB:
            raise HTTPException(501, "Cloud media transfer requires the next Helper release")
        try:
            item = repository.get_media(media_id)
            result = await transports.for_device(device).push_media(
                Path(item["storage_path"]),
                item["filename"],
            )
        except KeyError as exc:
            raise HTTPException(404, "Media not found") from exc
        return ActionResult(action="push_media", result=result)

    @router.websocket("/ws/device/{token}")
    async def device_websocket(websocket: WebSocket, token: str) -> None:
        device = repository.find_device_by_token(token)
        if device is None:
            await websocket.close(code=4001, reason="Invalid device token")
            return
        await websocket.accept()
        connection = hub.register(device.id, websocket)
        repository.update_device_presence(device.id, status=DeviceStatus.ONLINE)
        await websocket.send_json(
            {
                "type": "welcome",
                "device_id": device.id,
                "server_time": datetime.now(timezone.utc).isoformat(),
            }
        )

        async def ping() -> None:
            while True:
                await asyncio.sleep(25)
                await websocket.send_json(
                    {"type": "server_ping", "ts": datetime.now(timezone.utc).isoformat()}
                )

        ping_task = asyncio.create_task(ping())
        try:
            while True:
                payload = json.loads(
                    await asyncio.wait_for(websocket.receive_text(), timeout=90)
                )
                message_type = payload.get("type")
                if message_type == "heartbeat":
                    repository.update_device_presence(
                        device.id,
                        status=DeviceStatus.ONLINE,
                        battery_level=payload.get("battery"),
                        helper=payload.get("helper") or None,
                    )
                    await websocket.send_json({"type": "heartbeat_ack"})
                elif message_type == "hello":
                    repository.update_device_presence(
                        device.id,
                        status=DeviceStatus.ONLINE,
                        helper=payload.get("helper") or {},
                    )
                elif "id" in payload:
                    connection.receive(payload)
        except Exception:
            pass
        finally:
            ping_task.cancel()
            if hub.unregister(device.id, connection.session_id):
                repository.set_status(device.id, DeviceStatus.OFFLINE)

    return router
