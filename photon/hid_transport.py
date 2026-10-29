"""Minimal hidapi transport for non-destructive device access checks."""

from __future__ import annotations

import errno
import os
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass
from typing import Any

from .host import is_windows, load_hid_backend

hid = load_hid_backend()


@dataclass(frozen=True)
class AccessResult:
    """Result of opening and immediately closing one hidapi path."""

    path: str
    status: str
    node_exists: bool
    exception_type: str | None = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class HidTransportError(OSError):
    """A bounded hidapi transport failure with a stable status."""

    def __init__(self, status: str, path: str, message: str):
        super().__init__(message)
        self.status = status
        self.path = path


class HidSession(AbstractContextManager["HidSession"]):
    """An opened hidapi device. It exposes raw report I/O only."""

    def __init__(self, device: Any, path: str):
        self._device = device
        self.path = path
        self._closed = False

    def __enter__(self) -> "HidSession":
        return self

    def write_report(self, report: bytes) -> int:
        if self._closed:
            raise HidTransportError("closed", self.path, "HID session is closed")
        try:
            return int(self._device.write(report))
        except Exception as exc:
            raise HidTransportError("write_error", self.path, str(exc)) from exc

    def read_report(self, max_length: int = 64, timeout_ms: int = 1000) -> bytes:
        if self._closed:
            raise HidTransportError("closed", self.path, "HID session is closed")
        try:
            return bytes(self._device.read(max_length, timeout_ms))
        except Exception as exc:
            raise HidTransportError("read_error", self.path, str(exc)) from exc

    def close(self) -> None:
        if not self._closed:
            try:
                self._device.close()
            finally:
                self._closed = True

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _path_text(path: str | bytes) -> str:
    if isinstance(path, bytes):
        return path.decode(errors="replace")
    return str(path)


def _path_bytes(path: str | bytes) -> bytes:
    """Return the native byte path required by hidapi's open_path()."""
    if isinstance(path, bytes):
        return path
    return path.encode() if is_windows() else os.fsencode(path)


def _errno_from_exception(exc: BaseException) -> int | None:
    value = getattr(exc, "errno", None)
    if isinstance(value, int):
        return value
    if exc.args and isinstance(exc.args[0], int):
        return exc.args[0]
    return None


def _classify_os_error(exc: OSError) -> str:
    value = _errno_from_exception(exc)
    if value in {errno.EACCES, errno.EPERM} or isinstance(exc, PermissionError):
        return "permission_denied"
    if value == errno.EBUSY:
        return "busy"
    return "transport_error"


class HidTransport:
    """Thin wrapper around hidapi; it does not read or write reports."""

    def __init__(self, device_factory: Any = None):
        self._device_factory = hid.device if device_factory is None else device_factory

    def probe_open_close(self, path: str | bytes) -> AccessResult:
        text_path = _path_text(path)
        # Windows device paths are interface strings, not file system nodes.
        node_exists = True if is_windows() else os.path.exists(text_path)
        if not node_exists:
            return AccessResult(text_path, "missing_node", False)

        device = self._device_factory()
        opened = False
        close_error: Exception | None = None
        try:
            device.open_path(_path_bytes(path))
            opened = True
        except PermissionError as exc:
            return AccessResult(text_path, "permission_denied", True, type(exc).__name__, str(exc))
        except OSError as exc:
            return AccessResult(text_path, _classify_os_error(exc), True, type(exc).__name__, str(exc))
        except Exception as exc:  # hidapi bindings may use non-OSError exceptions
            return AccessResult(text_path, "transport_error", True, type(exc).__name__, str(exc))
        finally:
            if opened:
                try:
                    device.close()
                except Exception as exc:
                    # Closing is part of this probe: report a close failure rather
                    # than claiming the transport was fully usable.
                    close_error = exc

        if close_error is not None:
            return AccessResult(text_path, "close_error", True, type(close_error).__name__, str(close_error))
        return AccessResult(text_path, "opened", True)

    def open_session(self, path: str | bytes) -> HidSession:
        """Open a device for bounded raw report exchanges."""
        text_path = _path_text(path)
        if not is_windows() and not os.path.exists(text_path):
            raise HidTransportError("missing_node", text_path, "HID node does not exist")
        device = self._device_factory()
        try:
            device.open_path(_path_bytes(path))
        except PermissionError as exc:
            raise HidTransportError("permission_denied", text_path, str(exc)) from exc
        except OSError as exc:
            status = _classify_os_error(exc)
            message = str(exc)
            if is_windows() and status == "transport_error":
                # hidapi reports a bare "open failed" on Windows, whatever the cause.
                message = f"{message}; the device may be held by another program"
            raise HidTransportError(status, text_path, message) from exc
        except Exception as exc:
            raise HidTransportError("transport_error", text_path, str(exc)) from exc
        return HidSession(device, text_path)
