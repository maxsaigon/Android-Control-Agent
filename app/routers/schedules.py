"""API router for schedule management (CRUD + toggle)."""

from fastapi import APIRouter, HTTPException
from sqlmodel import Session, select

from app.database import engine
from app.models import (
    Schedule, ScheduleCreate, ScheduleUpdate, ScheduleRead, Device,
)
from app.services.scheduler import scheduler

router = APIRouter(prefix="/api/schedules", tags=["schedules"])


@router.get("", response_model=list[ScheduleRead])
def list_schedules():
    """List all schedules."""
    with Session(engine) as session:
        schedules = session.exec(
            select(Schedule).order_by(Schedule.device_id, Schedule.start_time)
        ).all()
        return schedules


@router.post("", response_model=ScheduleRead, status_code=201)
def create_schedule(data: ScheduleCreate):
    """Create a new schedule."""
    with Session(engine) as session:
        # Verify device exists
        device = session.get(Device, data.device_id)
        if not device:
            raise HTTPException(404, f"Device {data.device_id} not found")

        # Auto-generate command for script mode
        command = data.command
        if data.execution_mode == "script" and not command:
            command = f"Script: {data.action}"

        sched = Schedule(
            device_id=data.device_id,
            name=data.name,
            action=data.action,
            execution_mode=data.execution_mode,
            command=command,
            template=data.template or (data.action if data.execution_mode == "script" else None),
            start_time=data.start_time,
            end_time=data.end_time,
            days_of_week=data.days_of_week,
            repeat_count=data.repeat_count,
            random_delay_min=data.random_delay_min,
            random_delay_max=data.random_delay_max,
            script_count=data.script_count,
            script_view_time=data.script_view_time,
            script_like_chance=data.script_like_chance,
            max_steps=data.max_steps,
        )

        # Calculate initial next_run
        from datetime import datetime, timezone
        sched.next_run = scheduler._calculate_next_run(
            sched, datetime.now(timezone.utc)
        )

        session.add(sched)
        session.commit()
        session.refresh(sched)
        return sched


@router.get("/{schedule_id}", response_model=ScheduleRead)
def get_schedule(schedule_id: int):
    """Get a specific schedule."""
    with Session(engine) as session:
        sched = session.get(Schedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")
        return sched


@router.put("/{schedule_id}", response_model=ScheduleRead)
def update_schedule(schedule_id: int, data: ScheduleUpdate):
    """Update a schedule."""
    with Session(engine) as session:
        sched = session.get(Schedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")

        # Apply updates
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(sched, key, value)

        # Recalculate next_run if timing changed
        timing_fields = {
            "start_time", "end_time", "days_of_week",
            "random_delay_min", "random_delay_max",
        }
        if timing_fields & set(update_data.keys()):
            from datetime import datetime, timezone
            sched.next_run = scheduler._calculate_next_run(
                sched, datetime.now(timezone.utc)
            )

        session.add(sched)
        session.commit()
        session.refresh(sched)
        return sched


@router.delete("/{schedule_id}")
def delete_schedule(schedule_id: int):
    """Delete a schedule."""
    with Session(engine) as session:
        sched = session.get(Schedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")
        session.delete(sched)
        session.commit()
        return {"ok": True, "deleted": schedule_id}


@router.post("/{schedule_id}/toggle", response_model=ScheduleRead)
def toggle_schedule(schedule_id: int):
    """Toggle a schedule's enabled state."""
    with Session(engine) as session:
        sched = session.get(Schedule, schedule_id)
        if not sched:
            raise HTTPException(404, "Schedule not found")

        sched.enabled = not sched.enabled

        # Recalculate next_run when re-enabling
        if sched.enabled:
            from datetime import datetime, timezone
            sched.next_run = scheduler._calculate_next_run(
                sched, datetime.now(timezone.utc)
            )
        else:
            sched.next_run = None

        session.add(sched)
        session.commit()
        session.refresh(sched)
        return sched
