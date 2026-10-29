"""Event-driven Windows monitoring: device arrivals and power events feed ``DeviceMonitor``.

Arrivals come from ``CM_Register_Notification`` on the HID device interface class, which
works in a service (no window, no user session) and needs no polling. The notification
callback only queues the interface path; the monitor thread does the rest.
"""

from __future__ import annotations

import ctypes
import logging
import queue
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import DEFAULT_CONFIG_PATH, resolve_color
from .g733_notifications import G733NotificationManager
from .host import Guid
from .monitor import LATE_RETRY_DELAYS_SECONDS, DeviceMonitor, target_for_event
from .receiver_notifications import ReceiverNotificationManager


LOGGER = logging.getLogger(__name__)

GUID_DEVINTERFACE_HID = "4d1e55b2-f16f-11cf-88cb-001111000030"
CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE = 0
CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL = 0
CR_SUCCESS = 0
# Layout of CM_NOTIFY_EVENT_DATA for a device interface: FilterType and Reserved (two
# DWORDs), the interface class GUID, then the NUL-terminated symbolic link.
EVENT_DATA_LINK_OFFSET = 8 + 16

ARRIVAL = "arrival"
RESUME = "resume"
STOP = "stop"

_VID_PID = re.compile(r"VID_([0-9A-F]{4})&PID_([0-9A-F]{4})", re.IGNORECASE)
_INTERFACE_SUFFIX = re.compile(r"&MI_[0-9A-F]{2}", re.IGNORECASE)


def parse_interface_arrival(action: int, event_data: bytes) -> str | None:
    """The symbolic link of a device interface arrival, or None for any other notification."""
    if action != CM_NOTIFY_ACTION_DEVICEINTERFACEARRIVAL or len(event_data) <= EVENT_DATA_LINK_OFFSET:
        return None
    if int.from_bytes(event_data[:4], "little") != CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE:
        return None
    raw = event_data[EVENT_DATA_LINK_OFFSET:]
    raw = raw[: len(raw) - len(raw) % 2]
    link = raw.decode("utf-16-le", errors="replace").split("\x00", 1)[0]
    return link or None


def instance_id_from_link(link: str) -> str:
    r"""``\\?\HID#VID_..#7&..#{guid}`` -> ``HID\VID_..\7&..`` (the device instance ID)."""
    text = link[4:] if link.startswith("\\\\?\\") else link
    text = text.rsplit("#{", 1)[0]
    return text.replace("#", "\\")


def _no_instance(_link: str) -> str | None:
    return None


@dataclass
class Arrival:
    """A HID interface arrival shaped like the udev device ``DeviceMonitor`` already handles.

    ``ID_PATH`` is the USB device instance without its interface suffix, resolved lazily so
    that an unrelated device never costs a configuration-manager lookup.
    """

    path: str
    resolve_instance: Callable[[str], str | None] = _no_instance
    _identity: str | None = field(default=None, init=False, repr=False)

    def _vid_pid(self) -> tuple[str, str] | None:
        found = _VID_PID.search(self.path)
        return (found.group(1).lower(), found.group(2).lower()) if found else None

    @property
    def sys_path(self) -> str:
        return self.path

    def get(self, name: str) -> str | None:
        ids = self._vid_pid()
        if name == "ID_VENDOR_ID":
            return ids[0] if ids else None
        if name == "ID_MODEL_ID":
            return ids[1] if ids else None
        if name == "ID_PATH":
            if self._identity is None:
                self._identity = self.resolve_instance(self.path) or self._fallback_identity()
            return self._identity
        return None

    def _fallback_identity(self) -> str:
        ids = self._vid_pid()
        return f"usb:{ids[0]}:{ids[1]}" if ids else self.path


class CmSubscription:
    """``CM_Register_Notification`` on the HID interface class, calling ``sink(link)``.

    ``register``/``unregister`` are injectable so tests never touch the configuration manager.
    """

    def __init__(self, sink: Callable[[str], None], *, register=None, unregister=None):
        self._sink = sink
        self._register = register or _register_hid_arrival
        self._unregister = unregister or _unregister
        self._handle: Any = None
        self._callback_ref: Any = None

    def on_notification(self, action: int, event_data: bytes) -> None:
        link = parse_interface_arrival(action, event_data)
        if link is not None:
            self._sink(link)

    def start(self) -> None:
        self._handle, self._callback_ref = self._register(self.on_notification)

    def stop(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            self._unregister(handle)
        self._callback_ref = None


class _FilterUnion(ctypes.Union):
    _fields_ = [("ClassGuid", Guid), ("DeviceInstance", ctypes.c_wchar * 200), ("DeviceHandle", ctypes.c_void_p)]


class _NotifyFilter(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint32), ("Flags", ctypes.c_uint32), ("FilterType", ctypes.c_uint32),
                ("Reserved", ctypes.c_uint32), ("u", _FilterUnion)]


def _cfgmgr32():
    return ctypes.WinDLL("cfgmgr32", use_last_error=True)  # type: ignore[attr-defined]


def _register_hid_arrival(on_notification: Callable[[int, bytes], None]):
    """Subscribe to HID interface arrivals; returns the handle and the callback to keep alive."""
    callback_type = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        ctypes.c_uint32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32
    )

    def callback(_handle, _context, action, event_data, event_size):
        try:
            if event_data and event_size:
                on_notification(action, ctypes.string_at(event_data, event_size))
        except Exception:  # never let an exception cross into the configuration manager
            LOGGER.exception("failed handling a device notification")
        return 0

    native = callback_type(callback)
    notify_filter = _NotifyFilter()
    notify_filter.cbSize = ctypes.sizeof(_NotifyFilter)
    notify_filter.FilterType = CM_NOTIFY_FILTER_TYPE_DEVICEINTERFACE
    notify_filter.u.ClassGuid = Guid.from_string(GUID_DEVINTERFACE_HID)
    cfgmgr = _cfgmgr32()
    handle = ctypes.c_void_p()
    status = cfgmgr.CM_Register_Notification(ctypes.byref(notify_filter), None, native, ctypes.byref(handle))
    if status != CR_SUCCESS:
        raise OSError(f"CM_Register_Notification failed (CONFIGRET {status})")
    return handle, native


def _unregister(handle) -> None:
    _cfgmgr32().CM_Unregister_Notification(handle)


def usb_device_instance(link: str) -> str | None:
    r"""The USB device instance owning a HID interface, without its ``&MI_xx`` suffix.

    Walks up from the HID instance to the first ``USB\VID_..`` ancestor that is not an
    interface of a composite device, so every HID interface of one physical device shares
    the identity used for debouncing. None when the configuration manager cannot say.
    """
    cfgmgr = _cfgmgr32()
    node = ctypes.c_uint32()
    instance = instance_id_from_link(link)
    if cfgmgr.CM_Locate_DevNodeW(ctypes.byref(node), ctypes.c_wchar_p(instance), 0) != CR_SUCCESS:
        return None
    best: str | None = None
    for _ in range(4):
        parent = ctypes.c_uint32()
        if cfgmgr.CM_Get_Parent(ctypes.byref(parent), node, 0) != CR_SUCCESS:
            break
        buffer = ctypes.create_unicode_buffer(400)
        if cfgmgr.CM_Get_Device_IDW(parent, buffer, len(buffer), 0) != CR_SUCCESS:
            break
        ancestor = buffer.value
        if ancestor.upper().startswith("USB\\VID_"):
            best = ancestor
            if not _INTERFACE_SUFFIX.search(ancestor):
                break
        node = parent
    if best is None:
        return None
    return _INTERFACE_SUFFIX.sub("", best).lower()


class WindowsMonitor:
    """Subscribe to arrivals, apply at startup, then apply on arrivals and on resume.

    One queue carries arrivals (from the notification callback), resume events (from the
    service's power events) and the stop request, so a single thread applies and the
    existing retry and debounce rules of ``DeviceMonitor`` hold for all of them.
    """

    def __init__(
        self,
        monitor: DeviceMonitor,
        *,
        subscribe: Callable[[Callable[[str], None]], Any] | None = None,
        refresh: Callable[[], None] | None = None,
        resolve_instance: Callable[[str], str | None] = usb_device_instance,
        stop_event: threading.Event | None = None,
    ):
        self.monitor = monitor
        self._subscribe = subscribe or (lambda sink: CmSubscription(sink))
        self._refresh = refresh or (lambda: None)
        self._resolve_instance = resolve_instance
        self.stop_event = stop_event or threading.Event()
        self.events: queue.Queue[tuple[str, Any]] = queue.Queue()

    def post_resume(self) -> None:
        self.events.put((RESUME, None))

    def stop(self) -> None:
        self.stop_event.set()
        self.events.put((STOP, None))

    def _safe_refresh(self) -> None:
        try:
            self._refresh()
        except Exception:
            LOGGER.exception("could not refresh the HID++ notification listeners")

    def handle(self, kind: str, payload: Any) -> None:
        if kind == RESUME:
            LOGGER.info("resumed from sleep or hibernation; applying to every available device")
            self.monitor.apply_startup("resume")
            self._safe_refresh()
        elif kind == ARRIVAL:
            arrival = Arrival(payload, self._resolve_instance)
            if target_for_event(arrival) is None:
                return
            self.monitor.handle_event(arrival)
            self._safe_refresh()

    def run(self) -> None:
        subscription = self._subscribe(lambda link: self.events.put((ARRIVAL, link)))
        # Subscribe before the startup I/O, so a device enumerated while it runs is queued.
        subscription.start()
        try:
            self.monitor.apply_startup()
            self._safe_refresh()
            while True:
                kind, payload = self.events.get()
                if kind == STOP:
                    return
                try:
                    self.handle(kind, payload)
                except Exception:
                    LOGGER.exception("unexpected failure handling a %s event", kind)
        finally:
            subscription.stop()


def build_monitor(config_path: str, stop_event: threading.Event) -> WindowsMonitor:
    """The production wiring: configured color, real applies, HID++ notification managers."""
    from .monitor import _apply_available

    color = resolve_color(None, config_path)

    def interruptible_sleep(seconds: float) -> None:
        stop_event.wait(seconds)

    device_monitor = DeviceMonitor(
        color=color,
        apply=_apply_available,
        sleep=interruptible_sleep,
        late_retry_delays=LATE_RETRY_DELAYS_SECONDS,
        stop_event=stop_event,
    )
    receiver = ReceiverNotificationManager(device_monitor.handle_receiver_reconnect)
    g733 = G733NotificationManager(device_monitor.handle_g733_reconnect)

    def refresh() -> None:
        from tools.photon_enumerate import enumerate_devices

        devices = enumerate_devices()
        receiver.refresh(devices)
        g733.refresh(devices)

    return WindowsMonitor(device_monitor, refresh=refresh, stop_event=stop_event)


def run_foreground(config_path: str = str(DEFAULT_CONFIG_PATH)) -> int:
    """Run the monitor in a console until interrupted (a service runs it through the SCM)."""
    monitor = build_monitor(config_path, threading.Event())
    try:
        monitor.run()
    except KeyboardInterrupt:
        monitor.stop()
    return 0
