"""Resolve a device into its active transport."""

from ..config import Settings
from ..hub import DeviceHub
from ..models import DeviceView, TransportKind
from .adb import AdbTransport
from .base import DeviceTransport


class TransportRegistry:
    def __init__(self, settings: Settings, hub: DeviceHub):
        self.settings = settings
        self.hub = hub

    def for_device(self, device: DeviceView) -> DeviceTransport:
        if device.transport == TransportKind.CLOUD:
            return self.hub.get(device.id)
        return AdbTransport(self.settings.adb_path, device.address)
