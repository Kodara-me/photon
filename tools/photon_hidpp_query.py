#!/usr/bin/env python3
"""Send one harmless HID++ Root.GetFeature query to the current G733."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.g733 import G733_PRODUCT_ID, G733_VENDOR_ID
from photon.hid_transport import HidTransport
from photon.hidpp import FEATURE_SET, HidppClient, HidppError
from tools.photon_enumerate import enumerate_devices


def _g733_path() -> str:
    devices = enumerate_devices()
    matches = [
        interface["hidapi_path"]
        for device in devices
        if device["vendor_id"] == G733_VENDOR_ID and device["product_id"] == G733_PRODUCT_ID
        for interface in device["interfaces"]
    ]
    if not matches:
        raise RuntimeError("G733 hidraw interface was not found")
    if len(matches) > 1:
        raise RuntimeError(f"G733 has multiple candidate interfaces; select one after further inspection: {matches}")
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="store_true", help="print raw transmitted and received reports")
    args = parser.parse_args(argv)
    trace = (lambda direction, data: print(f"{direction}: {data.hex(' ')}", file=sys.stderr)) if args.trace else None
    path = _g733_path()
    with HidTransport().open_session(path) as session:
        response = HidppClient(session, force_long_reports=True, trace=trace).get_feature_index(FEATURE_SET)
    if response is None:
        print("G733 did not report HID++ Feature Set")
        return 1
    print(f"G733 HID++ response: feature=0x{response.feature_id:04x} index={response.index} flags=0x{response.flags:02x} version={response.version}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HidppError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
