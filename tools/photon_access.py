#!/usr/bin/env python3
"""Report read-only hidapi open/close access for supported Logitech interfaces."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Keep both ``python tools/photon_access.py`` and
# ``python -m tools.photon_access`` usable without installing the project.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.hid_transport import HidTransport
from tools.photon_enumerate import enumerate_devices


def _access_devices() -> list[dict[str, Any]]:
    transport = HidTransport()
    devices = enumerate_devices()
    for device in devices:
        for interface in device["interfaces"]:
            path = interface.get("hidapi_path") or interface.get("hidraw")
            result = transport.probe_open_close(path)
            interface["access"] = result.as_dict()
    return devices


def _format_error(access: dict[str, Any]) -> str:
    status = access["status"]
    if access.get("error"):
        return f"{status}: {access['exception_type']}: {access['error']}"
    return status


def format_text(devices: list[dict[str, Any]]) -> str:
    if not devices:
        return "No supported Logitech HID devices found."
    lines: list[str] = []
    for device in devices:
        lines.append(f"{device['product']} ({device['vendor_id']}:{device['product_id']})")
        if device.get("usb_path"):
            lines.append(f"  usb path: {device['usb_path']}")
        for interface in device["interfaces"]:
            label = interface.get("interface_number") or "?"
            path = interface.get("hidraw") or interface.get("hidapi_path") or "<unknown>"
            lines.append(f"  {path}  interface={label}  {_format_error(interface['access'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json", help="emit deterministic JSON")
    args = parser.parse_args(argv)
    devices = _access_devices()
    if args.as_json:
        print(json.dumps(devices, indent=2, sort_keys=True))
    else:
        print(format_text(devices))
    return 0


if __name__ == "__main__":
    sys.exit(main())
