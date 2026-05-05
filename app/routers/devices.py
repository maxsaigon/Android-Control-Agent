"""Device management API endpoints."""

from datetime import datetime, timezone
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Device,
    DeviceCreate,
    DeviceRead,
    DeviceStatus,
)
from app.services.device_manager import device_manager
from app.services.connection_watchdog import watchdog
from app.services.device_hub import device_hub
from app.models import DeviceToken

router = APIRouter(prefix="/api/devices", tags=["devices"])
logger = logging.getLogger(__name__)


def _cloud_display_name(base_name: str, device_id: int) -> str:
    clean = (base_name or "Cloud Device").strip()
    suffix = f"#{device_id}"
    if suffix in clean:
        return clean
    return f"{clean} {suffix}"


@router.get("", response_model=list[DeviceRead])
def list_devices(session: Session = Depends(get_session)):
    """List all registered devices."""
    devices = session.exec(select(Device)).all()
    return devices


@router.post("", response_model=DeviceRead, status_code=201)
def add_device(
    device_data: DeviceCreate, session: Session = Depends(get_session)
):
    """Register a new Android device."""
    # Check for duplicate IP
    existing = session.exec(
        select(Device).where(
            Device.ip_address == device_data.ip_address,
            Device.adb_port == device_data.adb_port,
        )
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Device at {device_data.ip_address}:{device_data.adb_port} already registered",
        )

    device = Device.model_validate(device_data)
    session.add(device)
    session.commit()
    session.refresh(device)
    return device


@router.get("/{device_id}", response_model=DeviceRead)
def get_device(device_id: int, session: Session = Depends(get_session)):
    """Get device details."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


@router.patch("/{device_id}", response_model=DeviceRead)
def update_device(device_id: int, body: dict, session: Session = Depends(get_session)):
    """Update device (e.g. rename)."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    if "name" in body:
        next_name = body["name"]
        if device.ip_address == "cloud" or device.adb_port == 0:
            next_name = _cloud_display_name(next_name, device.id)
        device.name = next_name
    session.add(device)
    session.commit()
    session.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: int, session: Session = Depends(get_session)):
    """Remove a device."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Cloud device lifecycle: deleting from webapp must invalidate helper token
    # so the phone has to request approval again.
    is_cloud = device.ip_address == "cloud" or device.adb_port == 0
    if is_cloud:
        tokens = session.exec(
            select(DeviceToken).where(DeviceToken.device_id == device.id)
        ).all()
        for t in tokens:
            t.is_active = False
            session.add(t)

        conn = device_hub.get_connection(device.id)
        if conn:
            conn.fail_all_pending("Device deleted from dashboard")
            try:
                await conn.ws.close(code=4001, reason="Device deleted from dashboard")
            except Exception:
                logger.debug("WS close failed for deleted device %s", device.id)
            device_hub.unregister(device.id, session_id=conn.session_id)

    # Unregister from watchdog
    watchdog.unregister_device(device.ip_address, device.adb_port)
    session.delete(device)
    session.commit()


@router.post("/{device_id}/connect")
async def connect_device(
    device_id: int, session: Session = Depends(get_session)
):
    """Connect to a device via ADB TCP/IP."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    success = await device_manager.connect(device.ip_address, device.adb_port)
    if success:
        # Fetch device info
        info = await device_manager.get_device_info(
            device.ip_address, device.adb_port
        )
        device.status = DeviceStatus.ONLINE
        device.last_seen = info.get("last_seen")
        device.android_version = info.get("android_version")
        device.device_model = info.get("device_model")
        device.battery_level = info.get("battery_level")
        session.add(device)
        session.commit()
        session.refresh(device)
        # Register with watchdog for keep-alive
        watchdog.register_device(device.ip_address, device.adb_port)
        return {"status": "connected", "device": DeviceRead.model_validate(device)}
    else:
        raise HTTPException(
            status_code=502,
            detail=f"Failed to connect to {device.ip_address}:{device.adb_port}",
        )


@router.get("/{device_id}/status")
async def device_status(
    device_id: int, session: Session = Depends(get_session)
):
    """Check device health."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Cloud devices must be checked via WebSocket hub, not ADB ping.
    # Their stored ip/port is ("cloud", 0), so ADB ping would always fail
    # and incorrectly force DB status to OFFLINE while WS is connected.
    if device.ip_address == "cloud" or device.adb_port == 0:
        reachable = device_hub.is_connected(device.id)
        if reachable:
            device.status = DeviceStatus.ONLINE
            conn = device_hub.get_connection(device.id)
            device.last_seen = conn.last_ping if conn else datetime.now(timezone.utc)
        else:
            device.status = DeviceStatus.OFFLINE
        session.add(device)
        session.commit()
        return {
            "device_id": device.id,
            "name": device.name,
            "reachable": reachable,
            "status": device.status,
            "battery_level": device.battery_level,
            "last_seen": device.last_seen,
        }

    reachable = await device_manager.ping(device.ip_address, device.adb_port)

    if reachable:
        info = await device_manager.get_device_info(
            device.ip_address, device.adb_port
        )
        device.status = DeviceStatus.ONLINE
        device.last_seen = info.get("last_seen")
        device.battery_level = info.get("battery_level")
    else:
        device.status = DeviceStatus.OFFLINE

    session.add(device)
    session.commit()

    return {
        "device_id": device.id,
        "name": device.name,
        "reachable": reachable,
        "status": device.status,
        "battery_level": device.battery_level,
        "last_seen": device.last_seen,
    }


@router.post("/scan")
async def scan_devices(
    body: dict,
    session: Session = Depends(get_session),
):
    """Scan a subnet for ADB-enabled Android devices."""
    subnet = body.get("subnet", "192.168.1")
    port = body.get("port", 5555)

    try:
        found = await device_manager.scan_subnet(subnet, port)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("LAN scan failed for subnet=%s port=%s", subnet, port)
        raise HTTPException(
            status_code=500,
            detail=f"Scan failed: {str(e) or type(e).__name__}",
        )

    # Check which IPs are already registered
    existing = session.exec(select(Device)).all()
    registered_ips = {f"{d.ip_address}:{d.adb_port}" for d in existing}

    for d in found:
        d["already_registered"] = f"{d['ip']}:{d['port']}" in registered_ips

    return {"subnet": subnet, "port": port, "devices": found}


@router.post("/{device_id}/setup-helper")
async def setup_helper(
    device_id: int, session: Session = Depends(get_session)
):
    """Install and configure AC Helper APK on a device.

    Steps: install APK → enable accessibility → launch → verify WebSocket.
    """
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    result = await device_manager.ensure_helper_apk(
        device.ip_address, device.adb_port
    )
    return {
        "device_id": device.id,
        "name": device.name,
        "helper": result,
    }
