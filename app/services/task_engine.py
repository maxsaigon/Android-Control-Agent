"""Task Execution Engine — routes tasks to ScriptRunner or AI Agent."""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.device_manager import device_manager

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result from a task execution."""

    success: bool
    reason: str
    steps: int
    step_log: list = field(default_factory=list)
    error: Optional[str] = None


class TaskEngine:
    """Routes tasks to ScriptRunner (free) or AI Agent (paid) based on execution mode."""

    def __init__(self):
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key

    async def execute(
        self,
        device_ip: str,
        device_port: int,
        command: str,
        use_reasoning: bool = True,
        max_steps: int = 20,
        on_step: callable = None,
        execution_mode: str = "auto",
        template: str | None = None,
        template_vars: dict | None = None,
    ) -> TaskResult:
        """
        Execute a task on an Android device.

        Routing logic:
        - "script": always use ScriptRunner (free)
        - "ai": always use AI Agent (paid)
        - "auto": use ScriptRunner if template matches, else AI Agent
        """
        # Cloud devices use "cloud:{id}" format — no ADB connection needed
        is_cloud = device_ip.startswith("cloud:")
        if is_cloud:
            device_target = device_ip  # "cloud:3"
        else:
            device_target = f"{device_ip}:{device_port}"
            # Ensure device is connected via ADB
            connected = await device_manager.ensure_connected(device_ip, device_port)
            if not connected:
                return TaskResult(
                    success=False,
                    reason="Device not reachable",
                    steps=0,
                    error=f"Cannot connect to {device_target}",
                )

        # Decide routing
        use_script = self._should_use_script(execution_mode, template)

        if use_script:
            return await self._execute_script(
                device_target, template or "", template_vars or {}, on_step
            )
        else:
            return await self._execute_ai(
                device_target, command, max_steps, on_step
            )

    def _should_use_script(self, mode: str, template: str | None) -> bool:
        """Decide whether to use ScriptRunner or AI Agent."""
        from app.services.script_runner import script_runner

        if mode == "script":
            return True
        elif mode == "ai":
            return False
        else:  # "auto"
            return bool(template and template in script_runner.AVAILABLE_SCRIPTS)

    async def _execute_script(
        self, device: str, script_name: str, params: dict, on_step
    ) -> TaskResult:
        """Execute via ScriptRunner (free)."""
        from app.services.script_runner import script_runner

        try:
            logger.info(f"🔧 Script mode: '{script_name}' on {device}")
            result = await script_runner.run(
                device=device,
                script_name=script_name,
                params=params,
                on_step=on_step,
            )
            return TaskResult(
                success=result.success,
                reason=result.reason,
                steps=result.steps,
                step_log=result.step_log,
                error=result.error,
            )
        except Exception as e:
            logger.exception(f"Script execution failed on {device}")
            return TaskResult(
                success=False, reason="Script error", steps=0, error=str(e)
            )

    async def _execute_ai(
        self, device: str, command: str, max_steps: int, on_step
    ) -> TaskResult:
        """Execute via AI Agent (paid)."""
        from app.services.adb_agent import adb_agent

        try:
            logger.info(f"🧠 AI mode: '{command[:80]}...' on {device}")
            result = await adb_agent.run(
                device=device,
                task=command,
                max_steps=max_steps,
                on_step=on_step,
            )
            return TaskResult(
                success=result.success,
                reason=result.reason,
                steps=result.steps,
                step_log=getattr(result, 'step_log', []),
                error=result.error,
            )
        except Exception as e:
            logger.exception(f"AI execution failed on {device}")
            return TaskResult(
                success=False, reason="Execution error", steps=0, error=str(e)
            )


# Singleton
task_engine = TaskEngine()
