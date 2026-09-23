"""Authenticated scrcpy sessions; each session reserves a device until disconnect."""

import asyncio
import logging
import struct
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlmodel import Session, select

from app.config import PROJECT_ROOT, settings
from app.database import engine
from app.models import Device, DeviceStatus, DeviceToken, User
from app.services.task_queue import task_queue

router = APIRouter(tags=["adb-live-stream"])
logger = logging.getLogger(__name__)
MAX_PACKET = 8 * 1024 * 1024


class Touch(BaseModel):
    action: Literal["touch"]
    phase: Literal[0, 1, 2, 3]
    pointerId: int = Field(ge=0, le=2**31 - 1)
    x: float = Field(ge=0, le=1, allow_inf_nan=False)
    y: float = Field(ge=0, le=1, allow_inf_nan=False)


class Key(BaseModel):
    action: Literal["key"]
    keyCode: Literal[3, 4, 187, 66, 67]  # Home, Back, Recents, Enter, Backspace


class Text(BaseModel):
    action: Literal["text"]
    text: str = Field(min_length=1, max_length=4096)


control_message = TypeAdapter(Annotated[Touch | Key | Text, Field(discriminator="action")])


def allowed_serial(device_id: int, user_id: int) -> str:
    with Session(engine) as session:
        user = session.get(User, user_id)
        device = session.get(Device, device_id)
        if not user or not device:
            raise PermissionError("Device unavailable")
        token = session.exec(select(DeviceToken).where(
            DeviceToken.device_id == device_id,
            DeviceToken.user_id == user_id,
            DeviceToken.is_active == True,
        )).first()
        # Legacy ADB devices have no owner column. Restrict unassigned ones to
        # the configured operator rather than granting every logged-in user access.
        if not token and user.username != settings.helper_owner_username:
            raise PermissionError("Device does not belong to this user")
        if device.ip_address == "cloud" or device.adb_port == 0:
            raise ValueError("Use LiveKit for this device")
        if device.status not in (DeviceStatus.ONLINE, DeviceStatus.BUSY):
            raise ValueError("Device is offline or awaiting ADB authorization")
        return f"{device.ip_address}:{device.adb_port}"


async def relay_worker(websocket: WebSocket, process):
    async def video():
        first = True
        while True:
            # Startup must finish promptly; an unchanged screen may then be idle.
            header = await asyncio.wait_for(process.stdout.readexactly(4), 20 if first else None)
            size = struct.unpack(">I", header)[0]
            if not 9 <= size <= MAX_PACKET:
                raise ValueError("Invalid gateway video packet")
            packet = await asyncio.wait_for(process.stdout.readexactly(size), 20)
            await asyncio.wait_for(websocket.send_bytes(packet), 10)
            first = False

    async def control():
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 32768:
                raise ValueError("Control message too large")
            message = control_message.validate_json(raw)
            process.stdin.write((message.model_dump_json() + "\n").encode())
            await asyncio.wait_for(process.stdin.drain(), 5)

    async def logs():
        async for line in process.stderr:
            logger.info("scrcpy: %s", line.decode(errors="replace").rstrip())

    workers = [asyncio.create_task(fn()) for fn in (video, control, logs)]
    try:
        done, _ = await asyncio.wait(workers, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


@router.websocket("/ws/adb/{device_id}")
async def adb_stream(websocket: WebSocket, device_id: int):
    user_id = websocket.session.get("user_id")
    origin = urlsplit(websocket.headers.get("origin", ""))
    if not user_id or origin.netloc != websocket.headers.get("host") or origin.scheme not in ("http", "https"):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    process = None
    try:
        serial = allowed_serial(device_id, int(user_id))
        if not settings.scrcpy_enabled:
            raise ValueError("ADB live control is disabled. Configure SCRCPY_ENABLED.")
        if not Path(settings.scrcpy_server_path).is_file():
            raise ValueError("scrcpy-server missing. Run gateway/scrcpy setup.")
        async with task_queue.manual_control(device_id):
            process = await asyncio.create_subprocess_exec(
                settings.scrcpy_node_path, str(PROJECT_ROOT / "gateway/scrcpy/worker.mjs"),
                serial, settings.scrcpy_server_path,
                settings.scrcpy_adb_host, str(settings.scrcpy_adb_port),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                async def check_access():
                    while True:
                        await asyncio.sleep(10)
                        if allowed_serial(device_id, int(user_id)) != serial:
                            raise PermissionError("Device connection changed")

                stream = asyncio.create_task(relay_worker(websocket, process))
                access = asyncio.create_task(check_access())
                try:
                    done, _ = await asyncio.wait(
                        [stream, access], timeout=settings.scrcpy_session_seconds,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise TimeoutError("Live Control session expired. Reopen to reconnect.")
                    for task in done:
                        task.result()
                finally:
                    stream.cancel()
                    access.cancel()
                    await asyncio.gather(stream, access, return_exceptions=True)
            finally:
                # Release the device lock only after the gateway is stopped.
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), 3)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
    except WebSocketDisconnect:
        pass
    except (ValueError, PermissionError, RuntimeError, OSError, ValidationError,
            asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
        detail = str(exc) or "Stream ended or timed out. Check ADB connection and gateway logs."
        try:
            await websocket.send_json({"error": detail})
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass
    finally:
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect, OSError):
            pass
