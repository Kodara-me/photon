"""Passive HID++ receiver link-state monitoring for the paired G502."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .host import is_windows
from .hid_transport import HidSession, HidTransport
from .hidpp import DEFAULT_DEVICE_INDEX, HidppClient, SHORT_REPORT_ID


LOGGER = logging.getLogger(__name__)
RECEIVER_PRODUCT_ID = "c547"
RECEIVER_NOTIFICATION_WRITE = 0x8000
# HID++ 1.0 notification register: WIRELESS | SOFTWARE_PRESENT.
RECEIVER_NOTIFICATION_FLAGS = b"\x00\x09\x00"
DEVICE_CONNECTION_SUB_ID = 0x41
LINK_NOT_ESTABLISHED = 0x40


@dataclass(frozen=True)
class ReceiverConnection:
    device_index: int
    online: bool


def parse_connection_notification(report: bytes) -> ReceiverConnection | None:
    """Parse a HID++ 1.0 receiver device-connection notification."""
    if len(report) < 7 or report[0] != SHORT_REPORT_ID or report[2] != DEVICE_CONNECTION_SUB_ID:
        return None
    if not 1 <= report[1] <= 6:
        return None
    return ReceiverConnection(report[1], online=not bool(report[4] & LINK_NOT_ESTABLISHED))


def enable_connection_notifications(session: HidSession) -> None:
    """Enable receiver wireless link-state reports once, without polling."""
    HidppClient(session, device_index=DEFAULT_DEVICE_INDEX).request(
        RECEIVER_NOTIFICATION_WRITE, RECEIVER_NOTIFICATION_FLAGS
    )


@dataclass
class ConnectionTransitions:
    """Only admit confirmed offline-to-online edges, never repeated online reports."""

    states: dict[int, bool] = field(default_factory=dict)

    def became_online(self, notification: ReceiverConnection) -> bool:
        previous = self.states.get(notification.device_index)
        self.states[notification.device_index] = notification.online
        return notification.online and previous is False


def receiver_notification_paths(devices: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return descriptor-verified vendor HID++ channels for supported receivers."""
    paths: list[str] = []
    # One Linux hidraw node carries both report IDs. Windows splits them into collections
    # with their own paths, and the link notifications are short reports (0x10).
    required = {SHORT_REPORT_ID} if is_windows() else {0x10, 0x11}
    for device in devices:
        if device.get("vendor_id") != "046d" or device.get("product_id") != RECEIVER_PRODUCT_ID:
            continue
        for interface in device.get("interfaces", ()):
            if required.issubset(set(interface.get("report_ids") or ())):
                path = interface.get("hidapi_path")
                if path and path not in paths:
                    paths.append(path)
    return tuple(paths)


class ReceiverNotificationWorker(threading.Thread):
    """Wait for receiver reports and apply only on a confirmed reconnect edge."""

    def __init__(self, path: str, on_reconnect: Callable[[ReceiverConnection], None]):
        super().__init__(name=f"photon-receiver-{path.rsplit('/', 1)[-1]}", daemon=True)
        self.path = path
        self._on_reconnect = on_reconnect
        self._transitions = ConnectionTransitions()

    def run(self) -> None:
        try:
            with HidTransport().open_session(self.path) as session:
                enable_connection_notifications(session)
                LOGGER.info("listening for receiver link transitions on %s", self.path)
                while True:
                    notification = parse_connection_notification(session.read_report(timeout_ms=1000))
                    if notification is not None and self._transitions.became_online(notification):
                        self._on_reconnect(notification)
        except Exception as exc:
            # Removal is expected; a subsequent hidraw add asks the manager to
            # start a fresh worker for the newly enumerated receiver.
            LOGGER.info("receiver link listener stopped for %s: %s", self.path, exc)


class ReceiverNotificationManager:
    """Maintain one passive receiver listener, restarting only after hotplug."""

    def __init__(self, on_reconnect: Callable[[ReceiverConnection], None]):
        self._on_reconnect = on_reconnect
        self._workers: dict[str, ReceiverNotificationWorker] = {}

    def refresh(self, devices: list[dict[str, Any]]) -> None:
        for path in receiver_notification_paths(devices):
            worker = self._workers.get(path)
            if worker is not None and worker.is_alive():
                continue
            worker = ReceiverNotificationWorker(path, self._on_reconnect)
            self._workers[path] = worker
            worker.start()
