"""Task management API endpoints — with batch, templates, and running tasks."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from app.database import get_session
from app.models import (
    Task, TaskCreate, TaskRead, TaskStatus,
    Device, BatchTaskCreate,
)
from app.services.task_queue import task_queue
from app.services.template_manager import template_manager

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("", response_model=list[TaskRead])
def list_tasks(
    device_id: int | None = None,
    status: TaskStatus | None = None,
    limit: int = 50,
    session: Session = Depends(get_session),
):
    """List tasks, optionally filtered by device or status."""
    query = select(Task)
    if device_id:
        query = query.where(Task.device_id == device_id)
    if status:
        query = query.where(Task.status == status)
    query = query.order_by(Task.created_at.desc()).limit(limit)  # type: ignore
    tasks = session.exec(query).all()
    return tasks


@router.get("/running", response_model=list[TaskRead])
def running_tasks(session: Session = Depends(get_session)):
    """List all currently running tasks."""
    tasks = session.exec(
        select(Task).where(Task.status.in_([TaskStatus.RUNNING, TaskStatus.PENDING]))  # type: ignore
    ).all()
    return tasks


@router.get("/queue-status")
def queue_status():
    """Get task queue status (running count, concurrency, device locks)."""
    return task_queue.status


@router.post("", response_model=TaskRead, status_code=201)
async def create_task(
    task_data: TaskCreate, session: Session = Depends(get_session)
):
    """Submit a new task for execution."""
    # Validate device exists
    device = session.get(Device, task_data.device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Resolve template if provided
    command = task_data.command
    if task_data.template:
        command = template_manager.render_command(
            name=task_data.template,
            base_command=task_data.command,
            variables=task_data.template_vars,
        )

    # Create task
    task = Task(
        device_id=task_data.device_id,
        command=command,
        template=task_data.template,
        use_reasoning=task_data.use_reasoning,
        execution_mode=task_data.execution_mode,
        max_steps=task_data.max_steps,
        max_retries=task_data.max_retries,
    )
    session.add(task)
    session.commit()
    session.refresh(task)

    # Submit to background queue
    await task_queue.submit(task.id)  # type: ignore

    return task


@router.post("/batch", status_code=201)
async def create_batch_tasks(
    batch: BatchTaskCreate, session: Session = Depends(get_session)
):
    """Submit the same task to multiple devices at once."""
    # Validate all devices exist
    created_tasks = []
    for device_id in batch.device_ids:
        device = session.get(Device, device_id)
        if not device:
            raise HTTPException(
                status_code=404, detail=f"Device {device_id} not found"
            )

    # Resolve template
    command = batch.command
    if batch.template:
        command = template_manager.render_command(
            name=batch.template,
            base_command=batch.command,
            variables=batch.template_vars,
        )

    # Create tasks for each device
    task_ids = []
    for device_id in batch.device_ids:
        task = Task(
            device_id=device_id,
            command=command,
            template=batch.template,
            use_reasoning=batch.use_reasoning,
            execution_mode=batch.execution_mode,
            max_steps=batch.max_steps,
            max_retries=batch.max_retries,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        created_tasks.append(TaskRead.model_validate(task))
        task_ids.append(task.id)

    # Submit all to queue (parallel execution across devices)
    await task_queue.submit_batch(task_ids)

    return {
        "submitted": len(created_tasks),
        "tasks": created_tasks,
    }


@router.get("/{task_id}", response_model=TaskRead)
def get_task(task_id: int, session: Session = Depends(get_session)):
    """Get task details."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int, session: Session = Depends(get_session)
):
    """Cancel a running task."""
    task = session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status not in (TaskStatus.RUNNING, TaskStatus.PENDING):
        raise HTTPException(
            status_code=400,
            detail=f"Task is not running (status: {task.status})",
        )

    cancelled = await task_queue.cancel(task_id)
    if cancelled:
        return {"status": "cancelled"}
    else:
        raise HTTPException(
            status_code=500, detail="Failed to cancel task"
        )
