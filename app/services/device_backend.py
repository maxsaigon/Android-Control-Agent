"""DeviceBackend — Abstract interface for Android device control.

Provides a unified API for controlling Android devices through
different transports (ADB subprocess, Accessibility WebSocket, etc.).

All concrete backends must implement this interface so that
adb_agent, script_runner, and tiktok_controller can work with
either backend transparently.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class UINode:
    """A UI element from the device screen."""
    index: int
    text: str
    resource_id: str
    class_name: str
    package: str
    content_desc: str
    clickable: bool
    scrollable: bool
    bounds: tuple[int, int, int, int]  # x1, y1, x2, y2

    @property
    def center(self) -> tuple[int, int]:
        return (
            (self.bounds[0] + self.bounds[2]) // 2,
            (self.bounds[1] + self.bounds[3]) // 2,
        )


class DeviceBackend(ABC):
    """Abstract interface for device control backends.

    Two implementations:
    - ADBBackend: wraps `adb shell` subprocess calls (existing behavior)
    - AccessibilityBackend: WebSocket client to helper APK on device
    """

    # --- Input actions ---

    @abstractmethod
    async def tap(self, device: str, x: int, y: int) -> str:
        """Tap at screen coordinates."""
        ...

    @abstractmethod
    async def swipe(
        self, device: str,
        x1: int, y1: int, x2: int, y2: int,
        duration_ms: int = 300,
    ) -> str:
        """Swipe from (x1,y1) to (x2,y2)."""
        ...

    @abstractmethod
    async def type_text(self, device: str, text: str) -> str:
        """Type text into the currently focused input field."""
        ...

    @abstractmethod
    async def key_event(self, device: str, keycode: str) -> str:
        """Send a key event (BACK, HOME, ENTER, etc.)."""
        ...

    # --- UI inspection ---

    @abstractmethod
    async def get_ui_tree(self, device: str) -> list[UINode]:
        """Get current UI hierarchy as a list of UINode objects."""
        ...

    @abstractmethod
    async def capture_screenshot(self, device: str, save_path: str = None) -> bytes:
        """Capture a screenshot. Returns raw image bytes (PNG or JPEG)."""
        ...

    @abstractmethod
    async def get_screen_size(self, device: str) -> tuple[int, int]:
        """Get device screen dimensions (width, height)."""
        ...

    # --- App management ---

    @abstractmethod
    async def launch_app(self, device: str, package: str) -> str:
        """Launch an app by package name."""
        ...

    @abstractmethod
    async def force_stop(self, device: str, package: str) -> str:
        """Force-stop an app."""
        ...

    @abstractmethod
    async def list_packages(self, device: str, third_party_only: bool = False) -> list[str]:
        """List installed package names."""
        ...

    # --- Device info ---

    @abstractmethod
    async def get_foreground_app(self, device: str) -> str:
        """Get the package name of the currently foreground app."""
        ...

    @abstractmethod
    async def get_device_info(self, device: str) -> dict:
        """Get device model, Android version, battery level."""
        ...

    @abstractmethod
    async def ping(self, device: str) -> bool:
        """Check if device is reachable and responsive."""
        ...

    # --- Raw command (ADB-specific fallback) ---

    async def raw_shell(self, device: str, *args: str) -> tuple[int, str, str]:
        """Run a raw shell command. Not all backends support this.

        Returns (returncode, stdout, stderr).
        Raises NotImplementedError if backend doesn't support raw commands.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support raw shell commands"
        )
