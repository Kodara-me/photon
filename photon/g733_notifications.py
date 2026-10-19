"""G733 reconnect detection using its ADC battery-status feature."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from .hid_transport import HidTransport
from .hidpp import HidppClient, LONG_REPORT_ID


LOGGER = logging.getLogger(__name__)
G733_PRODUCT_ID = "0afe"
STATUS_INTERVAL_SECONDS = 5.0
STATUS_TIMEOUT_MS = 1000
ADC_MEASUREMENT_FEATURE_INDEX = 0x08


class G733LivenessTransitions:
    """Admit a colour application only after offline becomes online."""

    def __init__(self):
        self.online: bool | None = None

    def became_online(self, online: bool) -> bool:
        previous = self.online
        self.online = online
        return online and previous is False


def g733_notification_paths(devices: list[dict[str, Any]]) -> tuple[str, ...]:
    """Return G733 HID++ channels which advertise the long report format."""
    paths: list[str] = []
    for device in devices:
        if device.get("vendor_id") != "046d" or device.get("product_id") != G733_PRODUCT_ID:
            continue
        for interface in device.get("interfaces", ()):
            if LONG_REPORT_ID not in set(interface.get("report_ids") or ()):
                continue
            path = interface.get("hidapi_path")
            if path and path not in paths:
                paths.append(path)
    return tuple(paths)


def adc_measurement_is_online(payload: bytes) -> bool:
    """A nonzero 0x1F20 battery voltage means the wireless headset is awake."""
    return len(payload) >= 3 and int.from_bytes(payload[:2], "big") > 0


def g733_is_online(path: str) -> bool:
    """Read one G733 ADC status value and close the HID handle.

    The USB receiver remains HID++-responsive while the physical headset is
    off, so Root.Ping is not useful here.  ADC measurement (feature 0x1F20,
    runtime index 8 on this G733) instead supplies the headset battery
    voltage: ``00 00`` means offline and a nonzero value means awake.
    """
    try:
        with HidTransport().open_session(path) as session:
            response = HidppClient(
                session, timeout_ms=STATUS_TIMEOUT_MS, force_long_reports=True
            ).feature_request(
                ADC_MEASUREMENT_FEATURE_INDEX
            )
        return adc_measurement_is_online(response.payload)
    except Exception as exc:
        LOGGER.debug("G733 liveness ping failed for %s: %s", path, exc)
        return False


class G733NotificationWorker(threading.Thread):
    """Check headset liveness at a low rate and notify on a reconnect edge."""

    def __init__(self, path: str, on_reconnect: Callable[[], None]):
        super().__init__(name=f"photon-g733-{path.rsplit('/', 1)[-1]}", daemon=True)
        self.path = path
        self._on_reconnect = on_reconnect
        self._stop_event = threading.Event()

    def run(self) -> None:
        transitions = G733LivenessTransitions()
        LOGGER.info("checking G733 battery link state every %.0fs on %s", STATUS_INTERVAL_SECONDS, self.path)
        while not self._stop_event.is_set():
            online = g733_is_online(self.path)
            if transitions.online is not online:
                LOGGER.info("G733 headset is %s", "online" if online else "offline")
            if transitions.became_online(online):
                self._on_reconnect()
            self._stop_event.wait(STATUS_INTERVAL_SECONDS)


class G733NotificationManager:
    """Maintain low-rate G733 liveness workers across physical re-enumeration."""

    def __init__(self, on_reconnect: Callable[[], None]):
        self._on_reconnect = on_reconnect
        self._workers: dict[str, G733NotificationWorker] = {}

    def refresh(self, devices: list[dict[str, Any]]) -> None:
        for path in g733_notification_paths(devices):
            worker = self._workers.get(path)
            if worker is not None and worker.is_alive():
                continue
            worker = G733NotificationWorker(path, self._on_reconnect)
            self._workers[path] = worker
            worker.start()
