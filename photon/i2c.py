"""Minimal Linux i2c-dev transport used by the Corsair RAM backend."""

from __future__ import annotations

import ctypes
import errno
import os
from pathlib import Path


I2C_M_RD = 0x0001
I2C_RDWR = 0x0707
I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
I2C_SMBUS_READ = 1
I2C_SMBUS_WRITE = 0
I2C_SMBUS_BYTE_DATA = 2
I2C_SMBUS_BLOCK_DATA = 5
I2C_SMBUS_I2C_BLOCK_DATA = 8
I2C_SMBUS_BLOCK_MAX = 32


class I2cError(OSError):
    """An I²C bus operation failed."""


class I2cMsg(ctypes.Structure):
    _fields_ = [
        ("addr", ctypes.c_uint16),
        ("flags", ctypes.c_uint16),
        ("length", ctypes.c_uint16),
        ("buffer", ctypes.POINTER(ctypes.c_uint8)),
    ]


class I2cRdwrData(ctypes.Structure):
    _fields_ = [
        ("messages", ctypes.POINTER(I2cMsg)),
        ("count", ctypes.c_uint32),
    ]


class I2cSmbusData(ctypes.Union):
    _fields_ = [
        ("byte", ctypes.c_uint8),
        ("word", ctypes.c_uint16),
        ("block", ctypes.c_uint8 * (I2C_SMBUS_BLOCK_MAX + 2)),
    ]


class I2cSmbusIoctlData(ctypes.Structure):
    _fields_ = [
        ("read_write", ctypes.c_uint8),
        ("command", ctypes.c_uint8),
        ("size", ctypes.c_uint32),
        ("data", ctypes.POINTER(I2cSmbusData)),
    ]


def _raise_i2c(exc: OSError, path: str) -> I2cError:
    return I2cError(exc.errno, f"I²C operation on {path} failed: {exc.strerror}")


class I2cBus:
    def __init__(self, path: str, opener=os.open):
        self.path = path
        try:
            self._fd = opener(path, os.O_RDWR | os.O_CLOEXEC)
        except OSError as exc:
            raise _raise_i2c(exc, path) from exc

    def close(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> "I2cBus":
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        self.close()

    def transfer(self, messages: list[tuple[int, bool, bytes | bytearray]]) -> list[bytes]:
        if self._fd is None:
            raise I2cError(errno.EBADF, "I²C bus is closed")
        buffers: list[ctypes.Array[ctypes.c_uint8]] = []
        descriptors: list[I2cMsg] = []
        reads: list[tuple[int, ctypes.Array[ctypes.c_uint8]]] = []
        for address, read, payload in messages:
            if read:
                buffer = (ctypes.c_uint8 * len(payload))()
                reads.append((len(reads), buffer))
            else:
                buffer = (ctypes.c_uint8 * len(payload))(*payload)
            buffers.append(buffer)
            descriptors.append(
                I2cMsg(
                    address,
                    I2C_M_RD if read else 0,
                    len(payload),
                    ctypes.cast(buffer, ctypes.POINTER(ctypes.c_uint8)),
                )
            )
        descriptor_array = (I2cMsg * len(descriptors))(*descriptors)
        request = I2cRdwrData(descriptor_array, len(descriptors))
        try:
            fcntl_ioctl(self._fd, I2C_RDWR, request)
        except OSError as exc:
            raise _raise_i2c(exc, self.path) from exc
        return [bytes(buffers[index]) for index, _buffer in reads]

    def read_register(self, address: int, register: int) -> int:
        data = I2cSmbusData()
        self._smbus(address, register, I2C_SMBUS_READ, I2C_SMBUS_BYTE_DATA, data)
        return data.byte

    def write_register(self, address: int, register: int, value: int) -> None:
        data = I2cSmbusData()
        data.byte = value
        self._smbus(address, register, I2C_SMBUS_WRITE, I2C_SMBUS_BYTE_DATA, data)

    def write_block(self, address: int, command: int, payload: bytes) -> None:
        if not 1 <= len(payload) <= I2C_SMBUS_BLOCK_MAX:
            raise ValueError(f"SMBus block writes must contain 1..{I2C_SMBUS_BLOCK_MAX} bytes")
        data = I2cSmbusData()
        data.block[0] = len(payload)
        data.block[1 : 1 + len(payload)] = payload
        self._smbus(address, command, I2C_SMBUS_WRITE, I2C_SMBUS_BLOCK_DATA, data)

    def _smbus(self, address: int, command: int, read_write: int, size: int, data: I2cSmbusData) -> None:
        if self._fd is None:
            raise I2cError(errno.EBADF, "I²C bus is closed")
        try:
            fcntl_ioctl(self._fd, I2C_SLAVE, address)
            request = I2cSmbusIoctlData(
                read_write,
                command,
                size,
                ctypes.pointer(data),
            )
            fcntl_ioctl(self._fd, I2C_SMBUS, request)
        except OSError as exc:
            raise _raise_i2c(exc, self.path) from exc

    def read_page(self, address: int, offset: int, size: int = 256) -> bytes:
        if not 0 <= offset <= 0xFF or not 1 <= size <= 256:
            raise ValueError("I²C EEPROM reads must use an 8-bit offset and 1..256 bytes")
        result = bytearray()
        remaining = size
        current = offset
        while remaining:
            length = min(remaining, I2C_SMBUS_BLOCK_MAX)
            data = I2cSmbusData()
            data.block[0] = length
            self._smbus(address, current, I2C_SMBUS_READ, I2C_SMBUS_I2C_BLOCK_DATA, data)
            actual = data.block[0]
            if actual != length:
                raise I2cError(errno.EIO, f"short SMBus block read on {self.path}")
            result.extend(data.block[1 : 1 + actual])
            current = (current + actual) & 0xFF
            remaining -= actual
        return bytes(result)


def fcntl_ioctl(fd: int, request: int, data: ctypes.Structure) -> int:
    """Small indirection that keeps the ioctl call replaceable in tests."""
    import fcntl

    return fcntl.ioctl(fd, request, data)


def available_buses(
    adapter_root: str | Path = "/sys/class/i2c-adapter",
    device_root: str | Path = "/dev",
) -> list[str]:
    root = Path(adapter_root)
    paths: list[str] = []
    if not root.exists():
        return paths
    for adapter in sorted(root.glob("i2c-*")):
        try:
            number = int(adapter.name[4:])
        except ValueError:
            continue
        device = Path(device_root) / f"i2c-{number}"
        if device.exists():
            paths.append(str(device))
    return paths
