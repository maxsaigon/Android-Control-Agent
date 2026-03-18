"""WebSocket endpoint for real-time task progress updates."""

import asyncio
import json

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlmodel import Session

from app.database import engine
from app.models import Task
from app.services.task_queue import task_queue

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/tasks/{task_id}")
async def task_progress(websocket: WebSocket, task_id: int):
    """
    WebSocket endpoint to stream real-time task execution updates.

    Connect to: ws://host:port/ws/tasks/{task_id}

    Events sent:
    - {"event": "queued"} — Task entered queue
    - {"event": "started"} — Task started executing
    - {"event": "step", "step_num": 1, "action": "key", ...}
    - {"event": "retry", "attempt": 1, "delay": 2}
    - {"event": "completed", "success": true, "reason": "...", "steps": 5}
    - {"event": "failed", "error": "..."}
    - {"event": "cancelled"}
    """
    await websocket.accept()

    # Send current task status immediately on connect
    with Session(engine) as session:
        task = session.get(Task, task_id)
        if task:
            await websocket.send_text(json.dumps({
                "event": "status",
                "task_id": task.id,
                "status": task.status.value,
                "steps_taken": task.steps_taken,
                "result": task.result,
            }))

    queue = task_queue.subscribe(task_id)
    try:
        while True:
            # Wait for updates from the task queue
            data = await queue.get()
            await websocket.send_text(json.dumps(data))

            # If task is done, close connection
            if data.get("event") in ("completed", "failed", "cancelled"):
                break
    except WebSocketDisconnect:
        pass
    finally:
        task_queue.unsubscribe(task_id, queue)

