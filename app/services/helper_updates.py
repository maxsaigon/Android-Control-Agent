"""Single-server, serial helper rollout with a canary and durable maintenance state."""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from sqlmodel import Session, select
from app.database import engine
from app.models import Device, HelperUpdateJob, HelperUpdatePolicy
from app.services.device_hub import device_hub
from app.services.helper_release import validated_helper_release

logger = logging.getLogger(__name__)
TERMINAL = {"succeeded", "failed", "needs_bootstrap", "cancelled"}


def now():
    return datetime.now(timezone.utc)


def blocking_reason(device_id, db_engine=None):
    with Session(db_engine or engine) as session:
        job = session.exec(select(HelperUpdateJob).where(
            HelperUpdateJob.device_id == device_id,
            HelperUpdateJob.blocks_control == True,
        )).first()
        return f"Helper update {job.id}: {job.state}. Check update status before controlling device." if job else None


def change(job_id, **values):
    with Session(engine) as session:
        job = session.get(HelperUpdateJob, job_id)
        for key, value in values.items():
            setattr(job, key, value)
        job.updated_at = now()
        session.add(job)
        session.commit()


def create_rollout(device_ids, release=None):
    release = release or validated_helper_release()
    ids = list(dict.fromkeys(device_ids))
    if not ids:
        raise ValueError("Select at least one device; the first is the canary")
    with Session(engine) as session:
        for device_id in ids:
            if not session.get(Device, device_id):
                raise ValueError(f"Device {device_id} not found")
        # A failed rollout must be resolved explicitly before another deployment.
        active = session.exec(select(HelperUpdateJob).where(
            HelperUpdateJob.state.notin_(list(TERMINAL))
        )).first()
        blocked = session.exec(select(HelperUpdateJob).where(HelperUpdateJob.blocks_control == True)).first()
        if active or blocked:
            raise ValueError("Resolve or retry the existing rollout before starting another")
        rollout_id = uuid.uuid4().hex
        for device_id in ids:
            session.add(HelperUpdateJob(rollout_id=rollout_id, device_id=device_id,
                version_code=release["version_code"], release_json=json.dumps(release)))
        policy = session.get(HelperUpdatePolicy, 1) or HelperUpdatePolicy()
        policy.last_version_code = release["version_code"]
        session.add(policy)
        session.commit()
        return rollout_id


class HelperUpdates:
    def __init__(self):
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    async def stop(self):
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Helper update monitor failed")
            await asyncio.sleep(10)

    async def tick(self):
        with Session(engine) as session:
            jobs = session.exec(select(HelperUpdateJob).order_by(HelperUpdateJob.id)).all()
        # Reconcile a late successful installation even after timeout/server restart.
        for job in jobs:
            if job.blocks_control and await self.verify_cloud(job):
                change(job.id, state="succeeded", error="", blocks_control=False)
                return
        for job in jobs:
            if job.state in TERMINAL:
                continue
            earlier = [j for j in jobs if j.rollout_id == job.rollout_id and j.id < job.id]
            if any(j.state != "succeeded" for j in earlier):
                continue  # Canary/previous-device failure stops the rest of the rollout.
            await self.process(job)
            return
        with Session(engine) as session:
            policy = session.get(HelperUpdatePolicy, 1)
            if not policy or not policy.automatic or not policy.canary_device_id:
                return
            latest_rollout = jobs[-1].rollout_id if jobs else None
            if any(j.state != "succeeded" for j in jobs if j.rollout_id == latest_rollout):
                return
            release = validated_helper_release()
            if release["version_code"] <= policy.last_version_code:
                return
            ids = [d.id for d in session.exec(select(Device)).all()]
            if policy.canary_device_id not in ids:
                return
            ids.remove(policy.canary_device_id)
            create_rollout([policy.canary_device_id, *ids], release)

    async def verify_cloud(self, job):
        conn = device_hub.get_connection(job.device_id)
        if not conn or conn.metadata.get("version_code") != job.version_code:
            return False
        if not conn.metadata.get("accessibility_ready"):
            return False
        try:
            await conn.send_command("get_screen_size")
            return True
        except (RuntimeError, ConnectionError, TimeoutError):
            return False

    async def process(self, job):
        from app.services.task_queue import task_queue
        from app.services.device_manager import device_manager
        with Session(engine) as session:
            device = session.get(Device, job.device_id)
        if not device:
            change(job.id, state="failed", error="Device was deleted", blocks_control=False)
            return
        is_cloud = device.adb_port == 0 or device.ip_address.startswith("cloud")
        if job.blocks_control and job.state != "queued":
            # Never re-send a potentially committed install after a restart/timeout.
            await self.observe(job)
            return
        conn = device_hub.get_connection(device.id)
        if is_cloud:
            if not conn:
                change(job.id, state="waiting_device")
                return
            if await self.verify_cloud(job):
                change(job.id, state="succeeded", error="")
                return
            if (conn.metadata.get("version_code") or 0) > job.version_code:
                change(job.id, state="failed", error="Refusing helper downgrade")
                return
            if "helper_update" not in conn.metadata.get("capabilities", []):
                change(job.id, state="needs_bootstrap", error="Install Helper 1.4.0 or later once via APK/ADB")
                return
        lock = task_queue._get_device_lock(device.id)
        if lock.locked():
            change(job.id, state="waiting_idle")
            return
        async with lock:
            if is_cloud:
                # A live stream persists between individual manual-control calls.
                try:
                    response = await conn.send_command("get_stream_status")
                    stream = response.get("result", {})
                    stream_state = stream.get("state", stream.get("status", "")) if isinstance(stream, dict) else str(stream)
                    if stream_state not in {"idle", "stopped", "error", "permission_denied", ""}:
                        change(job.id, state="waiting_idle", error="Close live stream before updating")
                        return
                except (RuntimeError, ConnectionError, TimeoutError) as exc:
                    change(job.id, state="failed", error=f"Cannot verify idle device: {exc}")
                    return
            change(job.id, state="downloading", blocks_control=True, started_at=now(), error="")
            release = json.loads(job.release_json)
            if not is_cloud:
                try:
                    result = await device_manager.install_helper_release(device.ip_address, device.adb_port, release)
                    if not result.get("verified"):
                        raise RuntimeError(result.get("error") or "Helper health check failed")
                    change(job.id, state="succeeded", blocks_control=False)
                except Exception as exc:
                    change(job.id, state="failed", error=str(exc))
                return
            try:
                await conn.send_command("helper_update", {**release, "job_id": job.id})
            except RuntimeError as exc:
                # Explicit device rejection means installation was not started.
                change(job.id, state="failed", error=str(exc), blocks_control=False)
            except (ConnectionError, TimeoutError) as exc:
                change(job.id, state="verifying", error=str(exc))

    async def observe(self, job):
        conn = device_hub.get_connection(job.device_id)
        update = conn.metadata.get("update", {}) if conn else {}
        if update.get("job_id") == job.id:
            state = update.get("state")
            if state == "failed":
                change(job.id, state="failed", error=update.get("error", "Installation failed"), blocks_control=False)
                return
            if state in {"downloading", "installing", "waiting_user_action"}:
                change(job.id, state=state, error=update.get("error", ""))
        started = job.started_at
        if started and (now() - started.replace(tzinfo=timezone.utc)).total_seconds() > 900:
            change(job.id, state="failed", error="No verified recovery within 15 minutes; device remains reserved. Repair/retry from dashboard.")


helper_updates = HelperUpdates()
