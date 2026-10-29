"""Platform seam: the host-specific choices shared by the Linux and Windows code paths."""

from __future__ import annotations

import ctypes
import os
import sys
import uuid
from importlib import import_module
from pathlib import Path
from types import ModuleType

LINUX_CONFIG_PATH = Path("/etc/photon/config.toml")
WINDOWS_DEFAULT_PROGRAM_DATA = r"C:\ProgramData"

# Known folder IDs (KNOWNFOLDERID). A service running as LocalSystem must not trust the
# environment variables of the process that started it, so folders are asked of the shell.
FOLDERID_PROGRAM_FILES = "905e63b6-c1bf-494e-b29c-65b732d3d21a"
FOLDERID_PROGRAM_FILES_X64 = "6d809377-6af0-444b-8957-a3773f02200e"
FOLDERID_PROGRAM_DATA = "62ab5d82-fdc1-4dc3-a9dd-070d1d495d97"

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


class Guid(ctypes.Structure):
    _fields_ = [("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
                ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8)]

    @classmethod
    def from_string(cls, text: str) -> "Guid":
        value = uuid.UUID(text)
        return cls(value.time_low, value.time_mid, value.time_hi_version,
                   (ctypes.c_ubyte * 8)(*value.bytes[8:]))


def known_folder(folder_id: str) -> Path | None:
    """Resolve a Windows known folder with ``SHGetKnownFolderPath``; None when it cannot be."""
    if not is_windows():
        return None
    try:
        shell32 = ctypes.WinDLL("shell32", use_last_error=True)  # type: ignore[attr-defined]
        ole32 = ctypes.WinDLL("ole32")  # type: ignore[attr-defined]
        shell32.SHGetKnownFolderPath.argtypes = [
            ctypes.POINTER(Guid), ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        shell32.SHGetKnownFolderPath.restype = ctypes.c_int32
        ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
        pointer = ctypes.c_void_p()
        guid = Guid.from_string(folder_id)
        if shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(pointer)) < 0:
            return None
        try:
            return Path(ctypes.wstring_at(pointer.value))
        finally:
            ole32.CoTaskMemFree(pointer)
    except (AttributeError, OSError, ValueError):
        return None


def program_files_folders(resolver=known_folder) -> list[Path]:
    """The ``Program Files`` folders of this host, from the shell and never the environment."""
    folders: list[Path] = []
    for folder_id in (FOLDERID_PROGRAM_FILES, FOLDERID_PROGRAM_FILES_X64):
        folder = resolver(folder_id)
        if folder is not None and folder not in folders:
            folders.append(folder)
    return folders


def program_data_folder(resolver=known_folder) -> Path:
    """``ProgramData`` from the shell, falling back to the environment and then ``C:\ProgramData``."""
    folder = resolver(FOLDERID_PROGRAM_DATA)
    if folder is not None:
        return folder
    return Path(os.environ.get("ProgramData") or WINDOWS_DEFAULT_PROGRAM_DATA)
