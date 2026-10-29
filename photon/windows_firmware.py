"""Windows firmware facts: the SMBIOS base-board product and memory part numbers.

Both are read-only. The parser works on raw SMBIOS bytes so tests can feed it a fake table.
"""

from __future__ import annotations

import ctypes
import struct

BASE_BOARD_KEY = r"HARDWARE\DESCRIPTION\System\BIOS"
BASE_BOARD_VALUE = "BaseBoardProduct"
SMBIOS_MEMORY_DEVICE = 17
SMBIOS_END_OF_TABLE = 127
MEMORY_PART_NUMBER_OFFSET = 0x1A
RSMB = 0x52534D42  # the raw SMBIOS firmware table provider
RAW_SMBIOS_HEADER = 8


def base_board_product() -> str:
    """Return the SMBIOS base-board product name (``BaseBoardProduct``)."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, BASE_BOARD_KEY) as key:
        value, _kind = winreg.QueryValueEx(key, BASE_BOARD_VALUE)
    return str(value).strip()


def parse_memory_part_numbers(table: bytes) -> list[str]:
    """Return the part number of every populated SMBIOS memory device (type 17)."""
    part_numbers: list[str] = []
    offset = 0
    while offset + 4 <= len(table):
        kind, length = table[offset], table[offset + 1]
        if length < 4 or offset + length > len(table):
            break
        end = offset + length
        # The string set follows the formatted area and ends with two NUL bytes.
        strings_end = table.find(b"\x00\x00", end)
        if strings_end < 0:
            strings_end = len(table)
        strings = table[end:strings_end].split(b"\x00") if strings_end > end else []
        if kind == SMBIOS_MEMORY_DEVICE and length > MEMORY_PART_NUMBER_OFFSET:
            index = table[offset + MEMORY_PART_NUMBER_OFFSET]
            if 1 <= index <= len(strings):
                text = strings[index - 1].decode("ascii", errors="replace").strip()
                if text:
                    part_numbers.append(text)
        if kind == SMBIOS_END_OF_TABLE:
            break
        offset = strings_end + 2
    return part_numbers


def raw_smbios_table() -> bytes:
    """Read the raw SMBIOS structure table through ``GetSystemFirmwareTable``."""
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemFirmwareTable.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p, ctypes.c_uint32]
    kernel32.GetSystemFirmwareTable.restype = ctypes.c_uint32
    size = kernel32.GetSystemFirmwareTable(RSMB, 0, None, 0)
    if size < RAW_SMBIOS_HEADER:
        raise OSError("SMBIOS data is unavailable")
    buffer = ctypes.create_string_buffer(size)
    if kernel32.GetSystemFirmwareTable(RSMB, 0, buffer, size) != size:
        raise OSError("SMBIOS data could not be read")
    raw = buffer.raw
    (declared,) = struct.unpack_from("<I", raw, 4)
    return raw[RAW_SMBIOS_HEADER : RAW_SMBIOS_HEADER + declared]


def memory_part_numbers() -> list[str]:
    return parse_memory_part_numbers(raw_smbios_table())
