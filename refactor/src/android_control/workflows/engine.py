"""One-lock-per-device deterministic workflow runner."""

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from ..database import Repository
from ..models import DeviceStatus, RunStatus, RunView, TransportKind, utc_now
from ..transports.registry import TransportRegistry
from .tiktok import WORKFLOWS


class WorkflowEngine:
    def __init__(self, repository: Repository, transports: TransportRegistry):
        self.repository = repository
        self.transports = transports
        self.locks: defaultdict[int, asyncio.Lock] = defaultdict(asyncio.Lock)
        self.tasks: dict[str, asyncio.Task[None]] = {}
        self.active_devices: dict[int, str] = {}

    def registry(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "title": item["title"],
                "description": item["description"],
                "parameters": item["parameters"],
            }
            for name, item in WORKFLOWS.items()
        ]

    def start(self, device_id: int, workflow: str, params: dict[str, Any]) -> RunView:
        if workflow not in WORKFLOWS:
            raise KeyError(workflow)
        self.repository.get_device(device_id)
        run = {
            "id": uuid.uuid4().hex[:12],
            "device_id": device_id,
            "workflow": workflow,
            "status": RunStatus.PENDING.value,
            "params": params,
            "steps": [],
            "created_at": utc_now(),
            "started_at": None,
            "finished_at": None,
            "error": None,
        }
        self.repository.insert_run(run)
        self.tasks[run["id"]] = asyncio.create_task(self._execute(run))
        return RunView(**run)

    async def _execute(self, run: dict[str, Any]) -> None:
        device_id = int(run["device_id"])
        try:
            async with self.locks[device_id]:
                self.active_devices[device_id] = run["id"]
                run["status"] = RunStatus.RUNNING.value
                run["started_at"] = utc_now()
                self.repository.set_status(device_id, DeviceStatus.BUSY)
                self.repository.update_run(run)

                device = self.repository.get_device(device_id)
                transport = self.transports.for_device(device)

                async def emit(action: str, detail: str, verified: bool) -> None:
                    run["steps"].append(
                        {
                            "number": len(run["steps"]) + 1,
                            "action": action,
                            "detail": detail,
                            "verified": verified,
                            "at": utc_now(),
                        }
                    )
                    self.repository.update_run(run)

                await asyncio.wait_for(
                    WORKFLOWS[run["workflow"]]["runner"](transport, run["params"], emit),
                    timeout=1200,
                )
                run["status"] = RunStatus.COMPLETED.value
        except asyncio.CancelledError:
            run["status"] = RunStatus.CANCELLED.value
        except Exception as exc:
            run["status"] = RunStatus.FAILED.value
            run["error"] = str(exc)
        finally:
            run["finished_at"] = utc_now()
            self.repository.update_run(run)
            try:
                if self.active_devices.get(device_id) == run["id"]:
                    self.active_devices.pop(device_id, None)
                    device = self.repository.get_device(device_id)
                    connected = self.transports.hub.connections.get(device_id)
                    if device.transport == TransportKind.CLOUD:
                        status = DeviceStatus.ONLINE if connected else DeviceStatus.OFFLINE
                    else:
                        status = DeviceStatus.ONLINE if run["status"] == RunStatus.COMPLETED else DeviceStatus.OFFLINE
                    self.repository.set_status(device_id, status)
            except KeyError:
                pass
            self.tasks.pop(run["id"], None)

    def cancel(self, run_id: str) -> None:
        task = self.tasks.get(run_id)
        if task is None:
            raise KeyError(run_id)
        run = self.repository.get_run(run_id)
        if run["status"] == RunStatus.PENDING:
            run["status"] = RunStatus.CANCELLED.value
            run["finished_at"] = utc_now()
            self.repository.update_run(run)
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        task.cancel()

    async def shutdown(self) -> None:
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
