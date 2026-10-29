"""SMBus access on Windows through PawnIO's signed Intel i801 module.

Photon uses ``PawnIOLib.dll`` when the user has installed PawnIO; it never installs,
updates or removes a driver. Every transaction holds the shared Windows SMBus mutex.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path

from .host import is_windows

SMBUS_MUTEX_NAME = "Global\\Access_SMBUS.HTP.Method"
MUTEX_WAIT_SECONDS = 5.0
LIBRARY_NAME = "PawnIOLib.dll"
MODULE_NAME = "SmbusI801.bin"
SMBUS_BUS_PATH = "smbus-i801"

# ioctl_smbus_xfer of the i801 module: address, direction, command and size cells,
# then the length-prefixed block data. Layout taken from OpenRGB's PawnIO SMBus
# driver; not yet checked on hardware.
IOCTL_SMBUS_XFER = b"ioctl_smbus_xfer"
XFER_HEADER_CELLS = 4
XFER_DATA_CELLS = 5
XFER_OUT_CELLS = 5
SMBUS_READ = 1
SMBUS_WRITE = 0
SMBUS_BYTE_DATA = 2
SMBUS_BLOCK_DATA = 5
SMBUS_BLOCK_MAX = 32

WAIT_OBJECT_0 = 0
WAIT_ABANDONED = 0x80


class RamUnavailable(RuntimeError):
    """The RAM cannot be reached; the message gives the reason."""


class SmbusMutexBusy(RamUnavailable):
    """Another program held the shared SMBus mutex for the whole bounded wait."""


def library_candidates(env: dict[str, str] | None = None) -> list[Path]:
    environment = os.environ if env is None else env
    roots = [environment.get("ProgramFiles"), environment.get("ProgramW6432")]
    return [Path(root) / "PawnIO" / LIBRARY_NAME for root in roots if root]


def find_library(env: dict[str, str] | None = None) -> Path | None:
    """Return the installed ``PawnIOLib.dll``, or None when PawnIO is not installed."""
    for candidate in library_candidates(env):
        if candidate.is_file():
            return candidate
    return None


def is_elevated() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return False


def module_blob_path() -> Path:
    """Locate the bundled i801 module (PyInstaller data, or the build tree)."""
    base = getattr(sys, "_MEIPASS", None)
    root = Path(base) if base else Path(__file__).resolve().parents[1] / "build"
    return root / "pawnio" / MODULE_NAME


class SmbusMutex:
    """The shared Windows SMBus mutex, with a bounded wait."""

    def __init__(self, name: str = SMBUS_MUTEX_NAME, wait_seconds: float = MUTEX_WAIT_SECONDS):
        self._wait_ms = int(wait_seconds * 1000)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        self._kernel32 = kernel32
        self._handle = kernel32.CreateMutexW(None, 0, name)
        if not self._handle:
            raise RamUnavailable(f"cannot open the SMBus mutex {name}")

    def __enter__(self) -> "SmbusMutex":
        result = self._kernel32.WaitForSingleObject(self._handle, self._wait_ms)
        if result not in (WAIT_OBJECT_0, WAIT_ABANDONED):
            raise SmbusMutexBusy(
                f"the SMBus is held by another program ({SMBUS_MUTEX_NAME} not released in "
                f"{self._wait_ms / 1000:g} s)"
            )
        return self

    def __exit__(self, *_args) -> None:
        self._kernel32.ReleaseMutex(self._handle)

    def close(self) -> None:
        if self._handle:
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


class PawnIoLibrary:
    """The few ``PawnIOLib.dll`` entry points Photon uses."""

    def __init__(self, path: Path):
        self._dll = ctypes.WinDLL(str(path))  # type: ignore[attr-defined]
        self._dll.pawnio_open.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        self._dll.pawnio_load.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t]
        self._dll.pawnio_execute.argtypes = [
            ctypes.c_void_p, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_uint64), ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_size_t),
        ]
        self._dll.pawnio_close.argtypes = [ctypes.c_void_p]
        self._handle = ctypes.c_void_p()

    def open(self, module: bytes) -> None:
        self._check(self._dll.pawnio_open(ctypes.byref(self._handle)), "open PawnIO")
        self._check(self._dll.pawnio_load(self._handle, module, len(module)), "load the i801 module")

    def execute(self, name: bytes, cells: list[int], out_cells: int) -> list[int]:
        in_buffer = (ctypes.c_uint64 * len(cells))(*cells)
        out_buffer = (ctypes.c_uint64 * out_cells)()
        returned = ctypes.c_size_t()
        self._check(
            self._dll.pawnio_execute(
                self._handle, name, in_buffer, len(cells), out_buffer, out_cells, ctypes.byref(returned)
            ),
            name.decode(),
        )
        return list(out_buffer)

    def close(self) -> None:
        if self._handle:
            self._dll.pawnio_close(self._handle)
            self._handle = ctypes.c_void_p()

    @staticmethod
    def _check(hresult: int, action: str) -> None:
        if hresult & 0x80000000:
            raise OSError(f"PawnIO failed to {action} (HRESULT 0x{hresult & 0xFFFFFFFF:08x})")


def open_smbus_library():
    """Open PawnIO with the i801 module; raise ``RamUnavailable`` with the reason if it cannot."""
    library_path = find_library()
    if library_path is None:
        raise RamUnavailable("PawnIO is not installed (PawnIOLib.dll not found); install PawnIO to drive the RAM")
    if not is_elevated():
        raise RamUnavailable("Photon is not elevated; run it from an elevated prompt to drive the RAM")
    module = module_blob_path()
    if not module.is_file():
        raise RamUnavailable(f"the PawnIO i801 module is missing ({module})")
    mutex = SmbusMutex()
    library = PawnIoLibrary(library_path)
    try:
        library.open(module.read_bytes())
    except OSError as exc:
        library.close()
        mutex.close()
        raise RamUnavailable(str(exc)) from exc
    return library, mutex


class PawnIoSmbus:
    """Same surface as ``photon.i2c.I2cBus`` (``read_register``, ``write_block``) on PawnIO.

    ``library`` and ``mutex`` are injectable so tests use fakes and never touch the driver.
    """

    def __init__(self, path: str = SMBUS_BUS_PATH, *, library=None, mutex=None):
        self.path = path
        self._owns = library is None
        if self._owns:
            library, mutex = open_smbus_library()
        elif mutex is None:
            raise ValueError("a library needs its SMBus mutex")
        self._library = library
        self._mutex = mutex

    def __enter__(self) -> "PawnIoSmbus":
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def close(self) -> None:
        if self._owns and self._library is not None:
            self._library.close()
            self._mutex.close()
        self._library = None

    def _transfer(self, address: int, read_write: int, command: int, size: int, block: bytes = b"") -> bytes:
        if self._library is None:
            raise OSError("SMBus is closed")
        data = block.ljust(XFER_DATA_CELLS * 8, b"\x00")
        cells = [address, read_write, command, size]
        cells += [int.from_bytes(data[i : i + 8], "little") for i in range(0, len(data), 8)]
        with self._mutex:
            out = self._library.execute(IOCTL_SMBUS_XFER, cells, XFER_OUT_CELLS)
        return b"".join(cell.to_bytes(8, "little") for cell in out)

    def read_register(self, address: int, register: int) -> int:
        return self._transfer(address, SMBUS_READ, register, SMBUS_BYTE_DATA)[0]

    def write_block(self, address: int, command: int, payload: bytes) -> None:
        if not 1 <= len(payload) <= SMBUS_BLOCK_MAX:
            raise ValueError(f"SMBus block writes must contain 1..{SMBUS_BLOCK_MAX} bytes")
        self._transfer(address, SMBUS_WRITE, command, SMBUS_BLOCK_DATA, bytes([len(payload)]) + payload)


def windows_bus_factory(path: str = SMBUS_BUS_PATH) -> PawnIoSmbus:
    if not is_windows():
        raise RamUnavailable("PawnIO is available on Windows only")
    return PawnIoSmbus(path)
