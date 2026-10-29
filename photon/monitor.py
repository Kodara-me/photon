"""Resident, event-driven RGB application for the system service."""

from __future__ import annotations

import argparse
import logging
import re
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

try:  # Linux-only event source
    import pyudev
except ImportError:  # pragma: no cover - Windows
    pyudev = None  # type: ignore[assignment]

from .config import DEFAULT_CONFIG_PATH, format_color, resolve_color
from .g733_notifications import G733NotificationManager
from .receiver_notifications import ReceiverConnection, ReceiverNotificationManager


LOGGER = logging.getLogger(__name__)
PRODUCT_TARGETS = {
    "0afe": "g733",
    "c095": "g502",
    # A paired G502 becomes a HID++ device behind its Lightspeed receiver;
    # the receiver itself is what udev reports on later USB reattachment.
    "c547": "g502",
    "c339": "keyboard",
}
RETRY_DELAYS_SECONDS = (0.5, 1.0, 2.0)
DEBOUNCE_SECONDS = 3.0


def _property(device: Any, name: str) -> str | None:
    """Read a udev property without assuming a concrete pyudev device type."""
    value = device.get(name)
    return str(value).lower() if value is not None else None


def target_for_event(device: Any) -> str | None:
    """Return the matching Photon target for a hidraw add event."""
    vendor = _property(device, "ID_VENDOR_ID")
    product = _property(device, "ID_MODEL_ID")
    if vendor is None or product is None:
        try:
            usb_parent = device.find_parent("usb", "usb_device")
            if usb_parent is not None:
                vendor = vendor or str(usb_parent.attributes.asstring("idVendor")).lower()
                product = product or str(usb_parent.attributes.asstring("idProduct")).lower()
        except (AttributeError, KeyError, OSError, UnicodeError):
            pass
    if vendor == "048d" and product == "5702":
        return "motherboard"
    if vendor != "046d":
        return None
    return PRODUCT_TARGETS.get(product or "")


def event_identity(device: Any) -> str:
    """Use a physical udev path so multi-interface devices debounce together."""
    identity = _property(device, "ID_PATH") or _property(device, "ID_SERIAL")
    if identity is not None:
        # hidraw interfaces have an ID_PATH suffix such as ``:1.2``. It is
        # not part of the physical USB device and must not defeat debouncing.
        return re.sub(r":\d+\.\d+$", "", identity)
    return str(getattr(device, "sys_path", "unknown-hidraw"))


@dataclass
class DeviceMonitor:
    """Apply at startup, then only after relevant device-arrival events."""

    color: tuple[int, int, int]
    apply: Callable[[tuple[int, int, int], str | None], Any]
    retry_delays: tuple[float, ...] = RETRY_DELAYS_SECONDS
    debounce_seconds: float = DEBOUNCE_SECONDS
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    seen: dict[str, float] = field(default_factory=dict)
    apply_lock: threading.Lock = field(default_factory=threading.Lock)

    def _apply(self, target: str | None, reason: str) -> bool:
        with self.apply_lock:
            for attempt in range(len(self.retry_delays) + 1):
                result = self.apply(self.color, target)
                if getattr(result, "applied", ()):
                    LOGGER.info("applied %s to %s after %s", format_color(self.color),
                                ", ".join(result.applied), reason)
                    return True
                if attempt == len(self.retry_delays):
                    failures = "; ".join(getattr(result, "failures", ())) or "no matching target found"
                    LOGGER.warning("could not apply RGB after %s: %s", reason, failures)
                    return False
                delay = self.retry_delays[attempt]
                LOGGER.info("RGB target not ready after %s; retrying in %.1fs", reason, delay)
                self.sleep(delay)
            return False  # pragma: no cover - loop always returns

    def apply_startup(self) -> bool:
        # Run each target independently so one missing device cannot prevent a
        # not-yet-ready peer from receiving its bounded startup retries.
        successful = False
        for target in ("g733", "g502", "keyboard", "ram", "motherboard"):
            successful = self._apply(target, "startup") or successful
        return successful

    def handle_event(self, device: Any) -> bool:
        target = target_for_event(device)
        if target is None:
            return False
        identity = event_identity(device)
        now = self.clock()
        previous = self.seen.get(identity)
        if previous is not None and now - previous < self.debounce_seconds:
            LOGGER.debug("ignoring duplicate hidraw event for %s", identity)
            return False
        self.seen[identity] = now
        return self._apply(target, f"udev add for {identity}")

    def handle_receiver_reconnect(self, notification: ReceiverConnection) -> bool:
        return self._apply("g502", f"receiver device 0x{notification.device_index:02x} reconnected")

    def handle_g733_reconnect(self) -> bool:
        return self._apply("g733", "G733 wake transition")

    def run(self, events: Iterable[Any]) -> None:
        self.apply_startup()
        for device in events:
            try:
                self.handle_event(device)
            except Exception:
                LOGGER.exception("unexpected failure handling hidraw udev event")


def _apply_available(color: tuple[int, int, int], target: str | None):
    from tools.photon_apply import apply_available

    return apply_available(color, only=target)


def run_monitor(*, config_path: str = str(DEFAULT_CONFIG_PATH)) -> None:
    """Run the blocking pyudev monitor loop used by the systemd unit."""
    color = resolve_color(None, config_path)
    monitor = DeviceMonitor(color=color, apply=_apply_available)

    context = pyudev.Context()
    udev_monitor = pyudev.Monitor.from_netlink(context)
    udev_monitor.filter_by(subsystem="hidraw")
    from tools.photon_enumerate import enumerate_devices

    # Subscribe before startup I/O so an arrival while initialization is slow
    # remains queued for the loop below.
    udev_monitor.start()
    monitor.apply_startup()
    receiver_notifications = ReceiverNotificationManager(monitor.handle_receiver_reconnect)
    g733_notifications = G733NotificationManager(monitor.handle_g733_reconnect)
    devices = enumerate_devices()
    receiver_notifications.refresh(devices)
    g733_notifications.refresh(devices)
    for device in iter(udev_monitor.poll, None):
        try:
            if getattr(device, "action", None) == "add":
                monitor.handle_event(device)
                devices = enumerate_devices()
                receiver_notifications.refresh(devices)
                g733_notifications.refresh(devices)
        except Exception:
            LOGGER.exception("unexpected failure handling hidraw udev event")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="TOML configuration path")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    run_monitor(config_path=args.config)
    return 0
