"""Anti-detection behavior module — humanize actions with randomized timing."""

import asyncio
import random
import logging

logger = logging.getLogger(__name__)


class HumanBehavior:
    """Adds human-like randomness to device interactions."""

    def __init__(
        self,
        min_delay: float = 1.5,
        max_delay: float = 5.0,
        tap_offset: int = 5,
        scroll_variance: float = 0.3,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.tap_offset = tap_offset
        self.scroll_variance = scroll_variance

    async def random_delay(self, action: str = "default") -> float:
        """Wait a random time before acting, varying by action type."""
        delays = {
            "tap": (1.0, 3.0),
            "type": (0.5, 1.5),
            "swipe": (1.5, 4.0),
            "scroll_down": (2.0, 5.0),
            "scroll_up": (2.0, 5.0),
            "key": (0.8, 2.0),
            "wait": (0, 0),  # Wait action handles its own delay
            "open_app": (1.0, 2.5),
            "complete": (0, 0),
        }
        lo, hi = delays.get(action, (self.min_delay, self.max_delay))
        if lo == 0 and hi == 0:
            return 0
        delay = random.uniform(lo, hi)
        logger.debug(f"🕐 Human delay: {delay:.1f}s before '{action}'")
        await asyncio.sleep(delay)
        return delay

    def jitter_tap(self, x: int, y: int) -> tuple[int, int]:
        """Add small random offset to tap coordinates."""
        dx = random.randint(-self.tap_offset, self.tap_offset)
        dy = random.randint(-self.tap_offset, self.tap_offset)
        return (max(0, x + dx), max(0, y + dy))

    def jitter_swipe_duration(self, base_ms: int = 300) -> int:
        """Randomize swipe duration."""
        variance = int(base_ms * self.scroll_variance)
        return base_ms + random.randint(-variance, variance)

    async def reading_pause(self, content_length: int = 0) -> float:
        """Simulate reading time based on content length."""
        # ~200 chars/second reading speed + randomness
        base = max(1.0, content_length / 200)
        pause = base + random.uniform(0.5, 2.0)
        pause = min(pause, 8.0)  # Cap at 8 seconds
        await asyncio.sleep(pause)
        return pause

    async def between_tasks_cooldown(self) -> float:
        """Cooldown between tasks to look natural."""
        cooldown = random.uniform(5.0, 30.0)
        logger.info(f"🕐 Cooldown between tasks: {cooldown:.1f}s")
        await asyncio.sleep(cooldown)
        return cooldown


# Singleton
human_behavior = HumanBehavior()
