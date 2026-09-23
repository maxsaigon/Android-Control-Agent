import asyncio
import importlib

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models import Device, DeviceStatus, Task, TaskStatus
from app.services.task_engine import TaskResult

queue_module = importlib.import_module('app.services.task_queue')


def test_waiting_device_does_not_consume_global_slot(tmp_path, monkeypatch):
    asyncio.run(_exercise_queue(tmp_path, monkeypatch))


async def _exercise_queue(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'queue.db'}")
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(queue_module, 'engine', engine)
    with Session(engine) as db:
        a = Device(name='A', ip_address='cloud:1', adb_port=0)
        b = Device(name='B', ip_address='cloud:2', adb_port=0)
        db.add_all([a, b])
        db.commit()
        jobs = [Task(device_id=a.id, command='first'), Task(device_id=a.id, command='second'),
                Task(device_id=b.id, command='other')]
        db.add_all(jobs)
        db.commit()
        ids = [job.id for job in jobs]
        device_id = a.id
    queue = queue_module.TaskQueue(max_concurrent=2)
    started = {job_id: asyncio.Event() for job_id in ids}
    release = asyncio.Event()

    async def execute(**kwargs):
        started[kwargs['task_id']].set()
        await release.wait()
        return TaskResult(success=True, reason='verified test result', steps=1)

    monkeypatch.setattr(queue, '_execute_with_retry', execute)
    try:
        await queue.submit(ids[0])
        await asyncio.wait_for(started[ids[0]].wait(), 1)
        await queue.submit(ids[1])
        await queue.submit(ids[2])
        await asyncio.wait_for(started[ids[2]].wait(), 1)
        assert not started[ids[1]].is_set()
        with Session(engine) as db:
            assert db.get(Task, ids[1]).status == TaskStatus.PENDING
        with pytest.raises(RuntimeError, match='busy'):
            async with queue.manual_control(device_id):
                pytest.fail('Manual command entered active workflow')
        await queue.cancel(ids[1])
        await asyncio.sleep(0)
        with Session(engine) as db:
            assert db.get(Device, device_id).status == DeviceStatus.BUSY
    finally:
        release.set()
        await asyncio.gather(*list(queue._running_tasks.values()))
    async with queue.manual_control(device_id):
        pass
