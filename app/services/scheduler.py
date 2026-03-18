"""Background scheduler service — checks schedules and auto-submits tasks."""

import asyncio
import logging
import random
from datetime import datetime, timezone, timedelta

from sqlmodel import Session, select

from app.database import engine
from app.models import Schedule, Task, TaskStatus

logger = logging.getLogger(__name__)

# Day name mapping
DAY_MAP = {
    0: "mon", 1: "tue", 2: "wed", 3: "thu",
    4: "fri", 5: "sat", 6: "sun",
}


class TaskScheduler:
    """Background service that checks schedules every 30s and submits tasks."""

    def __init__(self):
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self):
        """Start the scheduler loop."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("⏰ Task Scheduler started")

    async def stop(self):
        """Stop the scheduler loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("⏰ Task Scheduler stopped")

    async def _loop(self):
        """Main loop — check every 30 seconds."""
        while self._running:
            try:
                await self._check_schedules()
            except Exception as e:
                logger.error(f"⏰ Scheduler error: {e}")
            await asyncio.sleep(30)

    async def _check_schedules(self):
        """Check all enabled schedules and submit tasks if due."""
        now = datetime.now(timezone.utc)

        with Session(engine) as session:
            schedules = session.exec(
                select(Schedule).where(Schedule.enabled == True)  # noqa: E712
            ).all()

            for sched in schedules:
                # Calculate next_run if not set
                if sched.next_run is None:
                    sched.next_run = self._calculate_next_run(sched, now)
                    session.add(sched)
                    session.commit()
                    session.refresh(sched)
                    logger.info(
                        f"⏰ Schedule '{sched.name}' next run: {sched.next_run}"
                    )
                    continue

                # Check if it's time to run
                if now >= sched.next_run:
                    await self._submit_scheduled_task(sched, session)

                    # Update last_run and calculate next_run
                    sched.last_run = now
                    sched.next_run = self._calculate_next_run(sched, now)
                    session.add(sched)
                    session.commit()
                    logger.info(
                        f"⏰ Schedule '{sched.name}' executed, "
                        f"next: {sched.next_run}"
                    )

    def _calculate_next_run(
        self, sched: Schedule, now: datetime
    ) -> datetime:
        """Calculate the next run time with random offset within the window."""
        # Parse start/end times
        sh, sm = map(int, sched.start_time.split(":"))
        eh, em = map(int, sched.end_time.split(":"))

        # Start from today
        base = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # Find next valid day
        for day_offset in range(8):  # Check up to 7 days ahead
            candidate = base + timedelta(days=day_offset)
            day_name = DAY_MAP[candidate.weekday()]

            # Check if this day is valid
            if sched.days_of_week != "daily":
                allowed_days = [
                    d.strip().lower() for d in sched.days_of_week.split(",")
                ]
                if day_name not in allowed_days:
                    continue

            # Random time within [start_time, end_time]
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em
            if end_minutes <= start_minutes:
                end_minutes += 24 * 60  # Handle overnight windows

            random_minutes = random.randint(start_minutes, end_minutes)
            run_hour = (random_minutes // 60) % 24
            run_minute = random_minutes % 60

            # Add random delay for anti-detection
            delay = random.randint(sched.random_delay_min, sched.random_delay_max)
            run_time = candidate.replace(
                hour=run_hour, minute=run_minute, second=random.randint(0, 59)
            ) + timedelta(minutes=delay)

            # Must be in the future
            if run_time > now:
                return run_time

        # Fallback: tomorrow at start_time + random delay
        tomorrow = base + timedelta(days=1)
        delay = random.randint(sched.random_delay_min, sched.random_delay_max)
        return tomorrow.replace(hour=sh, minute=sm) + timedelta(minutes=delay)

    async def _submit_scheduled_task(
        self, sched: Schedule, session: Session
    ):
        """Create a Task from the schedule and submit it to the queue."""
        from app.services.task_queue import task_queue

        # Build command
        if sched.execution_mode == "script":
            command = f"Script: {sched.action}"
            template = sched.action
        else:
            command = sched.command or f"Custom AI: {sched.action}"
            template = sched.template

        # Create task
        task = Task(
            device_id=sched.device_id,
            command=command,
            template=template,
            execution_mode=sched.execution_mode,
            max_steps=sched.max_steps,
            max_retries=1,
        )
        session.add(task)
        session.commit()
        session.refresh(task)

        logger.info(
            f"⏰ Scheduled task #{task.id} for device {sched.device_id} "
            f"({sched.name}) — mode: {sched.execution_mode}"
        )

        # Submit to queue
        asyncio.create_task(task_queue.submit(task.id))

        # Handle repeat_count > 1: schedule additional runs
        if sched.repeat_count > 1:
            for i in range(1, sched.repeat_count):
                delay = random.randint(
                    sched.random_delay_min, sched.random_delay_max
                )
                asyncio.create_task(
                    self._delayed_submit(sched, session, delay * 60, i + 1)
                )

    async def _delayed_submit(
        self, sched: Schedule, parent_session: Session,
        delay_seconds: int, run_number: int
    ):
        """Submit a repeated task after a random delay."""
        await asyncio.sleep(delay_seconds)

        with Session(engine) as session:
            if sched.execution_mode == "script":
                command = f"Script: {sched.action}"
                template = sched.action
            else:
                command = sched.command or f"Custom AI: {sched.action}"
                template = sched.template

            task = Task(
                device_id=sched.device_id,
                command=command,
                template=template,
                execution_mode=sched.execution_mode,
                max_steps=sched.max_steps,
                max_retries=1,
            )
            session.add(task)
            session.commit()
            session.refresh(task)

            logger.info(
                f"⏰ Repeat #{run_number} of '{sched.name}' → "
                f"Task #{task.id} (delayed {delay_seconds // 60}m)"
            )

            from app.services.task_queue import task_queue
            asyncio.create_task(task_queue.submit(task.id))


# Singleton
scheduler = TaskScheduler()
