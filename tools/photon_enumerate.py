#!/usr/bin/env python3
"""Read-only enumeration of Photon' supported Logitech HID interfaces."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Any, Iterable

import hidraw as hid
import pyudev


SUPPORTED_DEVICES = {
    (0x046D, 0x0AFE): "G733 Gaming Headset",
    (0x046D, 0xC095): "G502 X PLUS",
    (0x046D, 0xC339): "PRO Gaming Keyboard",
    # A paired Lightspeed mouse is addressed through this receiver rather than
    # appearing as its direct-USB product ID.
    (0x046D, 0xC547): "Logitech USB Receiver",
}

_USB_INTERFACE_RE = re.compile(r"^(?P<usb>.+):(?P<interface>[^:]+)$")


def _text(value: Any) -> str | None:
    """Convert hidapi values to JSON-safe text."""
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return str(value)


def _hidraw_path(value: Any) -> str | None:
    text = _text(value)
    if not text:
        return None
    return text if text.startswith("/") else "/dev/" + text


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text().strip() or None
    except (OSError, UnicodeError):
        return None


def _sysfs_for_hidraw(hidraw: str | None) -> Path | None:
    if not hidraw:
        return None
    name = Path(hidraw).name
    link = Path("/sys/class/hidraw") / name / "device"
    try:
        return Path(os.path.realpath(link))
    except OSError:
        return None


def _usb_parent(sysfs_device: Path | None) -> tuple[Path | None, str | None, str | None]:
    """Return USB device path, USB physical name, and interface number."""
    if sysfs_device is None:
        return None, None, None

    interface_name: str | None = None
    usb_device: Path | None = None
    current = sysfs_device
    while current != current.parent:
        if current.name.count(":") == 1 and (current / "bInterfaceNumber").exists():
            interface_name = _read_text(current / "bInterfaceNumber") or current.name.rsplit(":", 1)[-1]
        if (_read_text(current / "idVendor") or "").lower() == "046d" and (current / "idProduct").exists():
            usb_device = current
            break
        current = current.parent

    if usb_device is None:
        return None, None, interface_name
    return usb_device, usb_device.name, interface_name


def _udev_properties(hidraw: str | None) -> dict[str, str]:
    if not hidraw:
        return {}
    try:
        context = pyudev.Context()
        sysfs_device = _sysfs_for_hidraw(hidraw)
        if sysfs_device is not None:
            device = pyudev.Devices.from_sys_path(context, str(sysfs_device))
        else:
            device = pyudev.Devices.from_device_file(context, hidraw)
    except (KeyError, OSError, ValueError, pyudev.DeviceNotFoundError):
        return {}
    return {str(key): str(value) for key, value in device.properties.items()}


def _interface_number(sysfs_device: Path | None, udev: dict[str, str]) -> str | None:
    if udev.get("ID_USB_INTERFACE_NUM"):
        return udev["ID_USB_INTERFACE_NUM"]
    if sysfs_device:
        current = sysfs_device
        while current != current.parent:
            value = _read_text(current / "bInterfaceNumber")
            if value is not None:
                return value
            current = current.parent
    return None


def _report_descriptor_size(sysfs_device: Path | None) -> int | None:
    if sysfs_device is None:
        return None
    try:
        return len((sysfs_device / "report_descriptor").read_bytes())
    except OSError:
        return None


def _report_ids(sysfs_device: Path | None) -> tuple[int, ...]:
    """Return HID report IDs advertised by a readable report descriptor."""
    if sysfs_device is None:
        return ()
    try:
        descriptor = (sysfs_device / "report_descriptor").read_bytes()
    except OSError:
        return ()
    # HID short item 0x85 is Report ID and is always followed by one byte.
    return tuple(sorted({descriptor[index + 1] for index in range(len(descriptor) - 1) if descriptor[index] == 0x85}))


def _merge_hidapi_entries(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate hidapi collection records by their shared hidraw path."""
    merged: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for raw in entries:
        path = _hidraw_path(raw.get("path"))
        if not path:
            continue
        item = merged.setdefault(
            path,
            {
                "path": path,
                "vendor_id": int(raw.get("vendor_id") or 0),
                "product_id": int(raw.get("product_id") or 0),
                "manufacturer": _text(raw.get("manufacturer_string")),
                "product": _text(raw.get("product_string")),
                "serial": _text(raw.get("serial_number")),
                "release_number": int(raw.get("release_number") or 0),
                "interface_number": raw.get("interface_number"),
                "collections": [],
            },
        )
        collection = {
            "usage_page": int(raw["usage_page"]) if raw.get("usage_page") is not None else None,
            "usage": int(raw["usage"]) if raw.get("usage") is not None else None,
        }
        if collection not in item["collections"]:
            item["collections"].append(collection)
    return list(merged.values())


def _record(raw: dict[str, Any]) -> dict[str, Any]:
    hidraw = raw["path"]
    sysfs_device = _sysfs_for_hidraw(hidraw)
    udev = _udev_properties(hidraw)
    usb_sysfs, usb_path, sysfs_interface = _usb_parent(sysfs_device)

    vendor_id = int(raw["vendor_id"])
    product_id = int(raw["product_id"])
    product = raw.get("product") or SUPPORTED_DEVICES.get((vendor_id, product_id))
    serial = raw.get("serial")
    if serial == "0000000000000000":
        serial = udev.get("ID_SERIAL_SHORT") or serial

    hid_uevent = {}
    if sysfs_device:
        for line in (_read_text(sysfs_device / "uevent") or "").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                hid_uevent[key] = value

    physical_path = hid_uevent.get("HID_PHYS") or udev.get("ID_PATH")
    unique = hid_uevent.get("HID_UNIQ") or serial
    interface_number = _interface_number(sysfs_device, udev) or sysfs_interface
    group_id = f"usb:{usb_path}:{vendor_id:04x}:{product_id:04x}" if usb_path else f"hid:{unique}:{vendor_id:04x}:{product_id:04x}"

    return {
        "group_id": group_id,
        "vendor_id": f"{vendor_id:04x}",
        "product_id": f"{product_id:04x}",
        "manufacturer": raw.get("manufacturer") or udev.get("ID_VENDOR"),
        "product": product,
        "serial": serial,
        "hidraw": hidraw,
        "hidapi_path": hidraw,
        "sysfs_path": str(sysfs_device) if sysfs_device else None,
        "usb_path": usb_path,
        "usb_sysfs_path": str(usb_sysfs) if usb_sysfs else None,
        "interface_number": interface_number,
        "hid_physical_path": physical_path,
        "hid_unique": unique,
        "report_descriptor_size": _report_descriptor_size(sysfs_device),
        "report_ids": _report_ids(sysfs_device),
        "release_number": raw.get("release_number"),
        "collections": sorted(raw["collections"], key=lambda x: (x["usage_page"] or -1, x["usage"] or -1)),
    }


def enumerate_devices(include_all: bool = False) -> list[dict[str, Any]]:
    raw_entries = list(hid.enumerate(0, 0))
    supported = []
    for entry in _merge_hidapi_entries(raw_entries):
        identity = (int(entry["vendor_id"]), int(entry["product_id"]))
        if include_all or identity in SUPPORTED_DEVICES:
            supported.append(_record(entry))

    groups: OrderedDict[str, dict[str, Any]] = OrderedDict()
    for interface in supported:
        group = groups.setdefault(
            interface["group_id"],
            {
                "group_id": interface["group_id"],
                "vendor_id": interface["vendor_id"],
                "product_id": interface["product_id"],
                "manufacturer": interface["manufacturer"],
                "product": interface["product"],
                "serial": interface["serial"],
                "usb_path": interface["usb_path"],
                "usb_sysfs_path": interface["usb_sysfs_path"],
                "interfaces": [],
            },
        )
        group["interfaces"].append({key: value for key, value in interface.items() if key not in {"group_id", "vendor_id", "product_id", "manufacturer", "product", "serial", "usb_path", "usb_sysfs_path"}})

    result = list(groups.values())
    for group in result:
        group["interfaces"].sort(key=lambda x: (x.get("interface_number") or "", x.get("hidraw") or ""))
    result.sort(key=lambda x: (x["vendor_id"], x["product_id"], x.get("usb_path") or "", x["group_id"]))
    return result


def _format_interface(interface: dict[str, Any]) -> list[str]:
    lines = [f"    - hidraw: {interface.get('hidraw') or '<unknown>'}"]
    for label, key in (
        ("interface", "interface_number"),
        ("hid physical path", "hid_physical_path"),
        ("hid unique", "hid_unique"),
        ("sysfs", "sysfs_path"),
        ("report descriptor", "report_descriptor_size"),
        ("report IDs", "report_ids"),
    ):
        if interface.get(key) is not None:
            suffix = " bytes" if key == "report_descriptor_size" else ""
            value = ", ".join(f"0x{item:02x}" for item in interface[key]) if key == "report_ids" else interface[key]
            lines.append(f"      {label}: {value}{suffix}")
    return lines


def format_text(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "No supported Logitech HID devices found."
    lines: list[str] = []
    for device in devices:
        lines.append(f"{device['product']} ({device['vendor_id']}:{device['product_id']})")
        for label, key in (("serial", "serial"), ("usb path", "usb_path"), ("usb sysfs", "usb_sysfs_path")):
            if device.get(key) is not None:
                lines.append(f"  {label}: {device[key]}")
        lines.append("  interfaces:")
        for interface in device["interfaces"]:
            lines.extend(_format_interface(interface))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit deterministic JSON")
    parser.add_argument("--all", action="store_true", help="include non-supported HID devices")
    args = parser.parse_args(argv)
    devices = enumerate_devices(include_all=args.all)
    if args.as_json:
        print(json.dumps(devices, indent=2, sort_keys=True))
    else:
        print(format_text(devices))
    return 0


if __name__ == "__main__":
    sys.exit(main())
