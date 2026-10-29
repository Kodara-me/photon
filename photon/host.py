"""Platform seam: the host-specific choices shared by the Linux and Windows code paths."""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

LINUX_CONFIG_PATH = Path("/etc/photon/config.toml")
WINDOWS_DEFAULT_PROGRAM_DATA = r"C:\ProgramData"

# Logitech HID++ report IDs.
SHORT_REPORT_ID = 0x10
LONG_REPORT_ID = 0x11


def is_windows() -> bool:
    return sys.platform == "win32"


def load_hid_backend() -> ModuleType:
    """Return the hidapi module for this host: ``hidraw`` on Linux, ``hid`` on Windows."""
    return import_module("hid" if is_windows() else "hidraw")


def default_config_path(env: dict[str, str] | None = None) -> Path:
    """Return ``/etc/photon/config.toml`` on Linux and ``%ProgramData%\Photon\config.toml`` on Windows."""
    if not is_windows():
        return LINUX_CONFIG_PATH
    environment = os.environ if env is None else env
    base = environment.get("ProgramData") or WINDOWS_DEFAULT_PROGRAM_DATA
    return Path(base) / "Photon" / "config.toml"


def infer_report_ids(usage_page: int | None, usage: int | None) -> tuple[int, ...]:
    """Infer the HID++ report IDs of one Windows top-level collection.

    Windows exposes each HID collection as its own path and hidapi gives no report
    descriptor without opening the device, so the vendor usage pages stand in for it:
    ``0xFF00`` usage 1 carries short reports and usage 2 long ones; the ``0xFF43``
    collections carry long ones. Live feature discovery still decides what answers.
    """
    if usage_page == 0xFF00 and usage == 1:
        return (SHORT_REPORT_ID,)
    if usage_page == 0xFF00 and usage == 2:
        return (LONG_REPORT_ID,)
    if usage_page == 0xFF43:
        return (LONG_REPORT_ID,)
    return ()


def is_hidpp_channel(report_ids: set[int] | frozenset[int] | tuple[int, ...]) -> bool:
    """Whether an interface is a receiver's HID++ channel.

    On Linux one hidraw node carries both reports; on Windows the short and long reports
    are separate collections, and Photon writes to the long one.
    """
    ids = set(report_ids)
    if is_windows():
        return LONG_REPORT_ID in ids
    return {SHORT_REPORT_ID, LONG_REPORT_ID}.issubset(ids)
