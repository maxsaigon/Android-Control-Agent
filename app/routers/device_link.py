import secrets
from datetime import datetime, timedelta, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import get_session
from sqlmodel import Session, select
from app.models import (
    DeviceLinkRequest,
    DeviceLinkRequestCreate,
    DeviceLinkRequestRead,
    DeviceLinkStatusRead,
    DeviceLinkStatus,
    Device,
    DeviceStatus,
    DeviceToken,
    User,
)
from app.services.device_identity import cloud_display_name

router = APIRouter(prefix="/api/device/link", tags=["Device Link"])


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_session_user(request: Request, session: Session) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user


def _expire_stale_pending(session: Session) -> None:
    now = _now_utc()
    expired = session.exec(
        select(DeviceLinkRequest).where(
            DeviceLinkRequest.status == DeviceLinkStatus.PENDING,
            DeviceLinkRequest.expires_at < now,
        )
    ).all()
    if not expired:
        return
    for item in expired:
        item.status = DeviceLinkStatus.EXPIRED
        session.add(item)
    session.commit()


@router.post("/request", response_model=DeviceLinkRequestRead)
def request_device_link(req: DeviceLinkRequestCreate, request: Request, session: Session = Depends(get_session)):
    """Android Helper requests to link device."""
    user = session.exec(select(User).where(User.username == req.username)).first()
    if not user:
        raise HTTPException(status_code=404, detail="Username not found")
    
    client_ip = request.client.host if request.client else None
    existing_requests = session.exec(
        select(DeviceLinkRequest).where(
            DeviceLinkRequest.username == req.username,
            (
                DeviceLinkRequest.installation_id == req.installation_id
                if req.installation_id
                else DeviceLinkRequest.device_name == req.device_name
            ),
            DeviceLinkRequest.status == DeviceLinkStatus.PENDING
        )
    ).all()
    for er in existing_requests:
        er.status = DeviceLinkStatus.EXPIRED
        session.add(er)
        
    helper = req.helper
    
    new_req = DeviceLinkRequest(
        request_id="lrq_" + secrets.token_urlsafe(16),
        username=req.username,
        user_id=user.id if user else None,
        installation_id=req.installation_id,
        device_name=req.device_name,
        device_model=req.device_model,
        android_version=req.android_version,
        sdk_int=req.sdk_int,
        manufacturer=req.manufacturer,
        helper_version_name=getattr(helper, 'version_name', None) if helper else None,
        helper_version_code=getattr(helper, 'version_code', None) if helper else None,
        helper_build_sha=getattr(helper, 'build_sha', None) if helper else None,
        status=DeviceLinkStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=15),
        client_fingerprint=client_ip
    )
    session.add(new_req)
    session.commit()
    session.refresh(new_req)
    
    return new_req

@router.get("/status/{request_id}", response_model=DeviceLinkStatusRead)
def get_device_link_status(request_id: str, session: Session = Depends(get_session)):
    """Android Helper polls status."""
    req = session.exec(select(DeviceLinkRequest).where(DeviceLinkRequest.request_id == request_id)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
        
    if req.status == DeviceLinkStatus.PENDING and _as_aware_utc(req.expires_at) < _now_utc():
        req.status = DeviceLinkStatus.EXPIRED
        session.add(req)
        session.commit()
        session.refresh(req)
        
    result = DeviceLinkStatusRead(status=req.status)
    if req.status == DeviceLinkStatus.APPROVED:
        device = session.get(Device, req.claimed_device_id) if req.claimed_device_id else None
        token_obj = session.exec(
            select(DeviceToken)
            .where(
                DeviceToken.device_id == req.claimed_device_id,
                DeviceToken.is_active == True,
            )
            .order_by(DeviceToken.id.desc())
        ).first() if req.claimed_device_id else None
        
        if device and token_obj:
            result.device_id = device.id
            result.device_name = device.name
            result.device_token = token_obj.token
            result.ws_url = f"wss://m.buonme.com/ws/device/{token_obj.token}"
            
    elif req.status == DeviceLinkStatus.REJECTED:
        result.message = req.reject_reason or "Rejected by admin"
        
    return result

@router.get("/requests", response_model=List[DeviceLinkRequestRead])
def list_pending_requests(request: Request, session: Session = Depends(get_session)):
    """WebApp lists pending requests."""
    user = _require_session_user(request, session)
    _expire_stale_pending(session)
        
    pending = session.exec(
        select(DeviceLinkRequest).where(
            DeviceLinkRequest.status == DeviceLinkStatus.PENDING,
            DeviceLinkRequest.user_id == user.id,
        )
    ).all()
    return pending

@router.post("/requests/{request_id}/accept")
def accept_request(request_id: str, request: Request, session: Session = Depends(get_session)):
    """WebApp accepts request."""
    user = _require_session_user(request, session)
        
    req = session.exec(select(DeviceLinkRequest).where(DeviceLinkRequest.request_id == request_id)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.user_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot approve another user's request")
        
    if req.status != DeviceLinkStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request is {req.status}")
        
    if _as_aware_utc(req.expires_at) < _now_utc():
        req.status = DeviceLinkStatus.EXPIRED
        session.commit()
        raise HTTPException(status_code=400, detail="Request expired")
        
    device = None
    if req.installation_id:
        device = session.exec(
            select(Device).where(
                Device.installation_id == req.installation_id,
            )
        ).first()

    if device is None:
        device = Device(
            installation_id=req.installation_id,
            name=req.device_name,
            ip_address="cloud",
            adb_port=0,
            android_version=req.android_version,
            device_model=req.device_model
        )
        session.add(device)
        session.commit()
        session.refresh(device)

    device.name = cloud_display_name(req.device_name, device.id)
    device.ip_address = "cloud"
    device.adb_port = 0
    device.android_version = req.android_version
    device.device_model = req.device_model
    session.add(device)

    old_tokens = session.exec(
        select(DeviceToken).where(
            DeviceToken.device_id == device.id,
            DeviceToken.is_active == True,
        )
    ).all()
    for old_token in old_tokens:
        old_token.is_active = False
        session.add(old_token)
            
    token_str = secrets.token_urlsafe(32)
    dt = DeviceToken(
        device_id=device.id,
        user_id=user.id,
        token=token_str,
        name=f"auto_token_{device.id}"
    )
    session.add(dt)
    
    req.status = DeviceLinkStatus.APPROVED
    req.claimed_device_id = device.id
    req.reviewed_at = _now_utc()
    req.reviewed_by_user_id = user.id
    
    session.add(req)
    session.commit()
    
    return {"status": "ok", "device_id": device.id}

@router.post("/requests/{request_id}/reject")
def reject_request(request_id: str, request: Request, session: Session = Depends(get_session)):
    """WebApp rejects request."""
    user = _require_session_user(request, session)
        
    req = session.exec(select(DeviceLinkRequest).where(DeviceLinkRequest.request_id == request_id)).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.user_id != user.id:
        raise HTTPException(status_code=403, detail="Cannot reject another user's request")
        
    if req.status != DeviceLinkStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Request is {req.status}")
        
    req.status = DeviceLinkStatus.REJECTED
    req.reviewed_at = _now_utc()
    req.reviewed_by_user_id = user.id
    
    session.add(req)
    session.commit()
    
    return {"status": "ok"}
