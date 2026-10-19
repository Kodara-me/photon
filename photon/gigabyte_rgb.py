"""Static RGB for the verified Gigabyte Z790 AORUS ELITE AX ITE controller.

Protocol and measured identities are recorded in docs/slices/18-fan-rgb-test.md.
"""

from __future__ import annotations

import fcntl
import os
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

Trace = Callable[[str, bytes], None]


BOARD_NAME = "Z790 AORUS ELITE AX"
# Measured host CC60 reply, 2026-10-02; see docs/slices/18-fan-rgb-test.md.
# The chip ID in this firmware is not the newer reference board-table identifier.
VERIFIED_INFO = {
    "product": 1,
    "controller_number": 0,
    "firmware": "3.5.5.0",
    "description": "IT5701-GIGABYTE V3.5.5.0",
    "chip_id": "0x57010100",
}
REPORT_ID = 0xCC
REPORT_LENGTH = 64
# Measured 2026-10-02: FF89:0010 / 5A:16 bytes; FF89:00CC / CC:63 bytes.
# Match the complete known descriptor rather than guessing a feature-report layout.
EXPECTED_DESCRIPTOR = bytes.fromhex(
    "06 89 ff 09 10 a1 01 85 5a 09 01 15 00 26 ff 00 75 08 95 10 b1 00 c0 "
    "06 89 ff 09 cc a1 01 85 cc 09 01 15 00 26 ff 00 75 08 95 3f b1 00 c0"
)
# Protocol-reference indexes, not a claim about the fans' physical wiring.
HEADERS = {"d-led1": 5, "d-led2": 6, "led-c1": 1, "led-c2": 4}
# Eight effect banks (CC20..CC27) in the protocol reference. Their physical
# correspondence on firmware 3.5.5.0 remains experimental, including the aliases above.
RGB_SLOTS = range(8)


@dataclass(frozen=True)
class Controller:
    node: Path
    sysfs: Path
    usb: Path


def discover_controller(
    hid_root: Path = Path("/sys/class/hidraw"),
    dev_root: Path = Path("/dev"),
    dmi_root: Path = Path("/sys/class/dmi/id"),
) -> Controller:
    if (dmi_root / "board_name").read_text().strip() != BOARD_NAME:
        raise RuntimeError(f"motherboard RGB is supported only on the verified {BOARD_NAME}")
    controllers = []
    for entry in sorted(hid_root.glob("hidraw*")):
        device = (entry / "device").resolve()
        metadata = dict(
            line.split("=", 1) for line in (device / "uevent").read_text().splitlines() if "=" in line
        )
        if metadata.get("HID_ID", "").upper() != "0003:0000048D:00005702":
            continue
        interface = next((p for p in device.parents if (p / "bInterfaceNumber").exists()), None)
        usb = next((p for p in device.parents if (p / "idVendor").exists()), None)
        if interface is None or usb is None:
            raise RuntimeError("ITE USB interface metadata is unavailable")
        if ((interface / "bInterfaceNumber").read_text().strip() != "00"
            or (usb / "idVendor").read_text().strip().lower() != "048d"
            or (usb / "idProduct").read_text().strip().lower() != "5702"):
            raise RuntimeError("ITE USB identity/interface does not match the verified controller")
        if (device / "report_descriptor").read_bytes() != EXPECTED_DESCRIPTOR:
            raise RuntimeError("ITE HID descriptor differs from the verified feature-report layout")
        controllers.append(Controller(dev_root / entry.name, device, usb))
    if len(controllers) != 1:
        raise RuntimeError(f"expected one verified ITE RGB controller; found {len(controllers)}")
    return controllers[0]


def require_rgb_apps_absent(proc_root: Path = Path("/proc")) -> None:
    running = []
    for entry in proc_root.glob("[0-9]*"):
        try:
            name = (entry / "comm").read_text().strip().lower()
        except FileNotFoundError:
            continue
        except PermissionError as exc:
            raise RuntimeError("cannot verify active RGB applications; run with sudo") from exc
        if name in {"openrgb", "solaar"}:
            running.append(f"{name} (PID {entry.name})")
    if running:
        raise RuntimeError("close RGB applications before testing: " + ", ".join(running))


def cc_report(command: int, value: int = 0) -> bytes:
    return bytes((REPORT_ID, command, value)) + bytes(REPORT_LENGTH - 3)


def static_reports(headers: list[str], color: tuple[int, int, int]) -> list[bytes]:
    if not headers or len(set(headers)) != len(headers) or any(h not in HEADERS for h in headers):
        raise ValueError("select distinct documented external lighting headers")
    return static_slot_reports([HEADERS[h] for h in headers], color)


def static_slot_reports(slots: list[int], color: tuple[int, int, int]) -> list[bytes]:
    if not slots or len(set(slots)) != len(slots) or any(s not in RGB_SLOTS for s in slots):
        raise ValueError("select distinct RGB slots in 0..7")
    if len(color) != 3 or any(not 0 <= c <= 255 for c in color):
        raise ValueError("RGB components must be 0..255")
    reports = []
    # CC32=0 enables built-in effects on both D_LED headers. Only selected effect
    # banks are staged/committed; this mode selection applies to both ARGB headers.
    if any(slot in (5, 6) for slot in slots):
        reports.append(cc_report(0x32))
    mask = 0
    for index in slots:
        mask |= 1 << index
        report = bytearray(REPORT_LENGTH)
        report[0:2] = bytes((REPORT_ID, 0x20 + index))
        struct.pack_into("<I", report, 2, 1 << index)
        report[11] = 1  # Hardware static effect.
        report[12] = 255  # Brightness; supplied color controls actual intensity.
        report[14:18] = bytes((color[2], color[1], color[0], 0))  # B,G,R,0 on wire.
        reports.append(bytes(report))
    commit = bytearray(REPORT_LENGTH)
    commit[0:2] = bytes((REPORT_ID, 0x28))
    struct.pack_into("<I", commit, 2, mask)
    reports.append(bytes(commit))
    return reports


def send_feature(fd: int, packet: bytes, *, trace: Trace | None = None) -> None:
    if len(packet) != REPORT_LENGTH or packet[0] != REPORT_ID:
        raise ValueError("invalid ITE feature-report framing")
    # Linux hidraw HIDIOCSFEATURE: _IOC(READ|WRITE, 'H', 0x06, length).
    buffer = bytearray(packet)
    if trace:
        trace("tx", packet)
    result = fcntl.ioctl(fd, 0xC0004806 | (len(buffer) << 16), buffer, True)
    if result != len(packet):
        raise RuntimeError(f"short feature-report write: {result}/{len(packet)}")


def query_info(fd: int, *, trace: Trace | None = None) -> dict:
    send_feature(fd, cc_report(0x60), trace=trace)  # Information selector; no lighting change.
    buffer = bytearray(REPORT_LENGTH)
    buffer[0] = REPORT_ID
    result = fcntl.ioctl(fd, 0xC0004807 | (len(buffer) << 16), buffer, True)
    if trace:
        trace("rx", bytes(buffer))
    if result != REPORT_LENGTH or buffer[0] != REPORT_ID:
        raise RuntimeError("unexpected ITE controller information report")
    return {
        "product": buffer[1],
        "controller_number": buffer[2],
        "strip_detect": buffer[3],
        "firmware": ".".join(str(v) for v in buffer[4:8]),
        "argb_count_codes": list(buffer[8:11]),
        "support_flags": buffer[11],
        "description": bytes(buffer[12:40]).split(b"\0", 1)[0].decode("ascii", errors="replace"),
        "chip_id": f"0x{struct.unpack_from('<I', buffer, 56)[0]:08x}",
    }


def validate_info(info: dict) -> None:
    mismatches = [name for name, expected in VERIFIED_INFO.items() if info.get(name) != expected]
    if mismatches:
        raise RuntimeError("controller identity differs from the verified host probe: " + ", ".join(mismatches))


def validate_opened_device(fd: int) -> None:
    # HIDIOCGRAWINFO from linux/hidraw.h: bustype, vendor, product.
    info = bytearray(8)
    fcntl.ioctl(fd, 0x80084803, info, True)
    if struct.unpack("=IHH", info) != (3, 0x048D, 0x5702):
        raise RuntimeError("opened device does not match the discovered USB RGB controller")


def _open_controller(controller: Controller) -> int:
    try:
        return os.open(controller.node, os.O_RDWR | os.O_CLOEXEC)
    except PermissionError as exc:
        raise RuntimeError(f"motherboard RGB access to {controller.node} requires root; run with sudo") from exc


def read_controller_info(*, trace: Trace | None = None) -> dict:
    """Query the identified controller, with no RGB changes, then close it."""
    controller = discover_controller()
    fd = _open_controller(controller)
    try:
        validate_opened_device(fd)
        return {**query_info(fd, trace=trace), "hidraw": str(controller.node), "board": BOARD_NAME}
    finally:
        os.close(fd)


def apply_static_color(color: tuple[int, int, int], *, trace: Trace | None = None) -> None:
    """Validate readiness/identity, apply to all eight RGB slots once, then close."""
    reports = static_slot_reports(list(RGB_SLOTS), color)
    controller = discover_controller()
    require_rgb_apps_absent()
    fd = _open_controller(controller)
    try:
        validate_opened_device(fd)
        # A complete, matching information reply is the readiness check. No lighting
        # reports are sent if the node/info is unavailable or the identity differs.
        validate_info(query_info(fd, trace=trace))
        for packet in reports:
            send_feature(fd, packet, trace=trace)
            time.sleep(0.05)  # Same bounded packet spacing as the successful test.
    finally:
        os.close(fd)

