"""Device management API endpoints."""

from datetime import datetime, timezone
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

router = APIRouter(prefix="/api/devices", tags=["devices"])


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


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int, session: Session = Depends(get_session)):
    """Remove a device."""
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
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
