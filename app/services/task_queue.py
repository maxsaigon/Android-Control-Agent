"""Enhanced background task queue with concurrency control and retry logic."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict

from sqlmodel import Session

from app.database import engine
from app.models import Task, TaskLog, TaskStatus, Device, DeviceStatus
from app.services.task_engine import task_engine, TaskResult

logger = logging.getLogger(__name__)

# Transient errors that should trigger retry
TRANSIENT_ERRORS = [
    "Device not reachable",
    "Cannot connect to",
    "Connection refused",
    "Connection reset",
    "Operation timed out",
    "screencap failed",
    "pull screenshot failed",
    "Failed to parse",
    "Max steps",
]


def _is_transient(error: str | None) -> bool:
    """Check if an error is transient and worth retrying."""
    if not error:
        return False
    return any(e.lower() in error.lower() for e in TRANSIENT_ERRORS)


class TaskQueue:
    """Manages background task execution across devices with concurrency control."""

    def __init__(self, max_concurrent: int = 5):
        self._running_tasks: Dict[int, asyncio.Task] = {}
        self._subscribers: Dict[int, list[asyncio.Queue]] = {}
        # Device locks: only 1 task per device at a time
        self._device_locks: Dict[int, asyncio.Lock] = {}
        # Global concurrency limiter
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # Live step data for REST polling (fallback when WebSocket unavailable)
        self._live_steps: Dict[int, dict] = {}

    def _get_device_lock(self, device_id: int) -> asyncio.Lock:
        """Get or create a lock for a specific device."""
        if device_id not in self._device_locks:
            self._device_locks[device_id] = asyncio.Lock()
        return self._device_locks[device_id]

    async def submit(self, task_id: int) -> None:
        """Submit a task for background execution."""
        if task_id in self._running_tasks:
            logger.warning(f"Task {task_id} is already running")
            return

        bg_task = asyncio.create_task(self._execute(task_id))
        self._running_tasks[task_id] = bg_task

    async def submit_batch(self, task_ids: list[int]) -> None:
        """Submit multiple tasks at once (parallel across different devices)."""
        for task_id in task_ids:
            await self.submit(task_id)

    async def cancel(self, task_id: int) -> bool:
        """Cancel a running task.

        Handles both active tasks (in _running_tasks) and orphaned tasks
        (stuck as 'running' in DB after server restart).
        """
        # 1. Cancel the asyncio task if it exists
        bg_task = self._running_tasks.get(task_id)
        if bg_task and not bg_task.done():
            bg_task.cancel()

        # 2. Always update DB status
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if task and task.status in (TaskStatus.RUNNING, TaskStatus.PENDING):
                task.status = TaskStatus.CANCELLED
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()
                logger.info(f"Task {task_id} cancelled in DB")
            else:
                return False

        # 3. Clean up
        await self._notify(task_id, {"event": "cancelled"})
        self._running_tasks.pop(task_id, None)
        return True

    def cleanup_orphaned(self) -> int:
        """Mark orphaned running/pending tasks as cancelled.

        Called on server startup to clean up tasks stuck from previous runs.
        Returns number of cleaned tasks.
        """
        count = 0
        with Session(engine) as session:
            from sqlmodel import select
            orphaned = session.exec(
                select(Task).where(
                    Task.status.in_([TaskStatus.RUNNING, TaskStatus.PENDING])  # type: ignore
                )
            ).all()
            for task in orphaned:
                if task.id not in self._running_tasks:
                    task.status = TaskStatus.CANCELLED
                    task.error = "Cancelled: server restarted"
                    task.completed_at = datetime.now(timezone.utc)
                    session.add(task)
                    count += 1
                    logger.info(f"Cleaned orphaned task {task.id}")
            session.commit()
        return count

    async def _execute(self, task_id: int) -> None:
        """Execute a task with device locking, concurrency control, and retry."""
        # Load task and device from DB
        with Session(engine) as session:
            task = session.get(Task, task_id)
            if not task:
                logger.error(f"Task {task_id} not found")
                return

            device = session.get(Device, task.device_id)
            if not device:
                task.status = TaskStatus.FAILED
                task.error = "Device not found"
                task.completed_at = datetime.now(timezone.utc)
                session.add(task)
                session.commit()
                return

            # Mark task as running
            task.status = TaskStatus.RUNNING
            task.started_at = datetime.now(timezone.utc)
            session.add(task)
            session.commit()

            command = task.command
            use_reasoning = task.use_reasoning
            execution_mode = task.execution_mode
            template = task.template
            max_steps = task.max_steps
            max_retries = task.max_retries
            device_id = device.id

            # Cloud devices: use cloud:{id} prefix instead of IP
            is_cloud = device.adb_port == 0 or device.ip_address.startswith("cloud")
            if is_cloud:
                device_ip = f"cloud:{device.id}"
                device_port = 0
            else:
                device_ip = device.ip_address
                device_port = device.adb_port

        await self._notify(task_id, {"event": "queued"})

        device_lock = self._get_device_lock(device_id)

        try:
            # Acquire device lock (1 task per device) + global semaphore
            async with self._semaphore:
                async with device_lock:
                    # Mark device busy
                    with Session(engine) as session:
                        device = session.get(Device, device_id)
                        if device:
                            device.status = DeviceStatus.BUSY
                            session.add(device)
                            session.commit()

                    await self._notify(task_id, {"event": "started"})

                    # 10-minute timeout to prevent stuck tasks
                    try:
                        result = await asyncio.wait_for(
                            self._execute_with_retry(
                                task_id=task_id,
                                device_ip=device_ip,
                                device_port=device_port,
                                command=command,
                                use_reasoning=use_reasoning,
                                execution_mode=execution_mode,
                                template=template,
                                max_steps=max_steps,
                                max_retries=max_retries,
                            ),
                            timeout=600,  # 10 minutes
                        )
                    except asyncio.TimeoutError:
                        logger.error(f"Task {task_id}: Timed out after 10 minutes")
                        result = TaskResult(
                            success=False,
                            reason="Timeout",
                            steps=0,
                            error="Task timed out after 10 minutes",
                        )

            # Update task in DB
            with Session(engine) as session:
                task = session.get(Task, task_id)
                if task:
                    task.status = (
                        TaskStatus.COMPLETED if result.success else TaskStatus.FAILED
                    )
                    task.result = result.reason
                    task.steps_taken = result.steps
                    task.error = result.error
                    task.completed_at = datetime.now(timezone.utc)
                    session.add(task)

                    # Persist step_log to TaskLog table
                    step_log = getattr(result, 'step_log', None) or []
                    for entry in step_log:
                        log = TaskLog(
                            task_id=task_id,
                            step=entry.get('step', 0) if isinstance(entry, dict) else getattr(entry, 'step_num', 0),
                            action=entry.get('action', '') if isinstance(entry, dict) else getattr(entry, 'action', ''),
                            detail=entry.get('detail', '') if isinstance(entry, dict) else getattr(entry, 'detail', ''),
                        )
                        session.add(log)

                    # Free up device
                    device = session.get(Device, device_id)
                    if device:
                        device.status = DeviceStatus.ONLINE
                        session.add(device)
                    session.commit()

            await self._notify(
                task_id,
                {
                    "event": "completed",
                    "success": result.success,
                    "reason": result.reason,
                    "steps": result.steps,
                },
            )

        except asyncio.CancelledError:
            logger.info(f"Task {task_id} was cancelled")
        except Exception as e:
            logger.exception(f"Task {task_id} failed with error")
            with Session(engine) as session:
                task = session.get(Task, task_id)
                if task:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    task.completed_at = datetime.now(timezone.utc)
                    session.add(task)

                    device = session.get(Device, device_id)
                    if device:
                        device.status = DeviceStatus.ONLINE
                        session.add(device)
                    session.commit()

            await self._notify(task_id, {"event": "failed", "error": str(e)})
        finally:
            self._running_tasks.pop(task_id, None)

    async def _execute_with_retry(
        self,
        task_id: int,
        device_ip: str,
        device_port: int,
        command: str,
        use_reasoning: bool,
        execution_mode: str,
        template: str | None,
        max_steps: int,
        max_retries: int,
    ) -> TaskResult:
        """Execute task with automatic retry for transient errors."""
        last_result = None
        for attempt in range(max_retries + 1):
            if attempt > 0:
                delay = min(2 ** attempt, 30)  # Exponential backoff, max 30s
                logger.info(
                    f"Task {task_id}: Retry {attempt}/{max_retries} "
                    f"in {delay}s..."
                )
                await self._notify(
                    task_id,
                    {"event": "retry", "attempt": attempt, "delay": delay},
                )
                await asyncio.sleep(delay)

                # Update retry count in DB
                with Session(engine) as session:
                    task = session.get(Task, task_id)
                    if task:
                        task.retry_count = attempt
                        session.add(task)
                        session.commit()

            # Step callback for real-time progress
            async def on_step(step):
                # Store in memory for REST polling fallback
                if task_id not in self._live_steps:
                    self._live_steps[task_id] = {"steps": [], "started_at": None}
                live = self._live_steps[task_id]
                live["current_step"] = step.step_num
                live["action"] = step.action
                live["detail"] = step.detail
                live["steps"].append({
                    "step_num": step.step_num,
                    "action": step.action,
                    "detail": step.detail,
                })
                # Keep only last 10 steps in memory
                if len(live["steps"]) > 10:
                    live["steps"] = live["steps"][-10:]

                # Incrementally update steps_taken in DB
                with Session(engine) as session:
                    task_obj = session.get(Task, task_id)
                    if task_obj:
                        task_obj.steps_taken = step.step_num
                        session.add(task_obj)
                        session.commit()

                await self._notify(
                    task_id,
                    {
                        "event": "step",
                        "step_num": step.step_num,
                        "action": step.action,
                        "detail": step.detail,
                    },
                )

            result = await task_engine.execute(
                device_ip=device_ip,
                device_port=device_port,
                command=command,
                use_reasoning=use_reasoning,
                execution_mode=execution_mode,
                template=template,
                max_steps=max_steps,
                on_step=on_step,
            )
            last_result = result

            if result.success:
                return result

            # Check if error is transient and retry-able
            if not _is_transient(result.error) and not _is_transient(result.reason):
                logger.info(f"Task {task_id}: Non-transient error, no retry")
                return result

            logger.warning(
                f"Task {task_id}: Transient error: {result.error or result.reason}"
            )

        return last_result  # Return last attempt's result

    # --- WebSocket subscription ---

    def subscribe(self, task_id: int) -> asyncio.Queue:
        """Subscribe to real-time updates for a task."""
        queue: asyncio.Queue = asyncio.Queue()
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)
        return queue

    def unsubscribe(self, task_id: int, queue: asyncio.Queue) -> None:
        """Unsubscribe from task updates."""
        if task_id in self._subscribers:
            self._subscribers[task_id].remove(queue)
            if not self._subscribers[task_id]:
                del self._subscribers[task_id]

    async def _notify(self, task_id: int, data: dict) -> None:
        """Notify all subscribers of a task update."""
        for queue in self._subscribers.get(task_id, []):
            await queue.put(data)
        # Clean up live steps on task completion
        if data.get("event") in ("completed", "failed", "cancelled"):
            self._live_steps.pop(task_id, None)

    def get_live_steps(self) -> Dict[int, dict]:
        """Get live step data for all running tasks (REST polling fallback)."""
        return dict(self._live_steps)

    def is_running(self, task_id: int) -> bool:
        """Check if a task is currently running."""
        bg = self._running_tasks.get(task_id)
        return bg is not None and not bg.done()

    @property
    def running_count(self) -> int:
        """Number of currently running tasks."""
        return sum(1 for t in self._running_tasks.values() if not t.done())

    @property
    def status(self) -> dict:
        """Get queue status."""
        return {
            "running_tasks": self.running_count,
            "max_concurrent": self._semaphore._value,
            "device_locks": list(self._device_locks.keys()),
        }


# Singleton
task_queue = TaskQueue()
