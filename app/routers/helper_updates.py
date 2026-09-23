"""Dashboard release selection, canary-first rollout and update history."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session, select
from app.database import engine
from app.models import HelperUpdateJob, HelperUpdatePolicy, User
from app.config import settings
from app.services.helper_updates import create_rollout, change, helper_updates
from app.services.device_hub import device_hub

router = APIRouter(prefix="/api/helper/updates", tags=["helper-updates"])


def require_owner(request):
    with Session(engine) as session:
        user = session.get(User, request.session.get("user_id"))
        if not user or user.username != settings.helper_owner_username:
            raise HTTPException(403, "Only the configured personal owner can manage helper updates")


class RolloutRequest(BaseModel):
    device_ids: list[int] = Field(min_length=1, max_length=100)


class PolicyRequest(BaseModel):
    automatic: bool
    canary_device_id: int | None = None


@router.get("")
def list_updates(request: Request):
    require_owner(request)
    with Session(engine) as session:
        jobs = session.exec(select(HelperUpdateJob).order_by(HelperUpdateJob.id.desc()).limit(100)).all()
        policy = session.get(HelperUpdatePolicy, 1) or HelperUpdatePolicy()
        return {"policy": policy, "jobs": [j.model_dump(exclude={"release_json"}) for j in jobs]}


@router.post("/rollout")
def rollout(body: RolloutRequest, request: Request):
    require_owner(request)
    try:
        return {"rollout_id": create_rollout(body.device_ids)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/policy")
def policy(body: PolicyRequest, request: Request):
    require_owner(request)
    with Session(engine) as session:
        if body.automatic:
            passed = session.exec(select(HelperUpdateJob).where(
                HelperUpdateJob.device_id == body.canary_device_id,
                HelperUpdateJob.state == "succeeded",
            )).first()
            if not passed:
                raise HTTPException(409, "First complete a verified update on the chosen canary")
        policy = session.get(HelperUpdatePolicy, 1) or HelperUpdatePolicy()
        policy.automatic = body.automatic
        policy.canary_device_id = body.canary_device_id
        session.add(policy)
        session.commit()
        return {"status": "saved"}


@router.post("/{job_id}/retry")
async def retry(job_id: int, request: Request):
    require_owner(request)
    with Session(engine) as session:
        job = session.get(HelperUpdateJob, job_id)
        if not job or job.state not in {"failed", "needs_bootstrap"}:
            raise HTTPException(409, "Only failed/bootstrap updates can be retried")
        from app.models import Device
        device = session.get(Device, job.device_id)
    if not device:
        raise HTTPException(404, "Device was deleted")
    conn = device_hub.get_connection(job.device_id)
    if device.adb_port == 0 or device.ip_address.startswith("cloud"):
        if await helper_updates.verify_cloud(job):
            change(job.id, state="succeeded", blocks_control=False, error="")
            return {"status": "succeeded"}
        if not conn:
            raise HTTPException(409, "Reconnect device before retrying")
        if conn.metadata.get("update", {}).get("state") in {"installing", "waiting_user_action", "downloading"}:
            raise HTTPException(409, "Resolve pending installation on the device first")
        if job.blocks_control and conn.metadata.get("update", {}).get("state") not in {"failed", "idle", "needs_permission"}:
            raise HTTPException(409, "Installation outcome is unknown; inspect device first")
    change(job.id, state="queued", error="")
    return {"status": "queued"}


@router.post("/rollouts/{rollout_id}/stop")
def stop_rollout(rollout_id: str, request: Request):
    """Stop unstarted work; never release an unresolved installation reservation."""
    require_owner(request)
    with Session(engine) as session:
        jobs = session.exec(select(HelperUpdateJob).where(HelperUpdateJob.rollout_id == rollout_id)).all()
        if not jobs:
            raise HTTPException(404, "Rollout not found")
        for job in jobs:
            if not job.blocks_control and job.state != "succeeded":
                job.state = "cancelled"
                session.add(job)
        policy = session.get(HelperUpdatePolicy, 1)
        if policy:
            policy.automatic = False
            session.add(policy)
        session.commit()
    return {"status": "stopped", "detail": "Unstarted updates cancelled; in-flight installs remain reserved"}
