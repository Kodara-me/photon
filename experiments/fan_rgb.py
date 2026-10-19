#!/usr/bin/env python3
"""One-shot RGB header test for this machine's Gigabyte Z790 AORUS ELITE AX."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.gigabyte_rgb import (
    BOARD_NAME, HEADERS, RGB_SLOTS, discover_controller, query_info,
    require_rgb_apps_absent, send_feature, static_slot_reports,
    validate_info, validate_opened_device,
)


def trace(direction: str, data: bytes) -> None:
    print(f"{direction}: {data.hex(' ')}", flush=True)


def parse_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#?[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError("color must be #RRGGBB")
    value = value.lstrip("#")
    return tuple(int(value[i:i+2], 16) for i in (0, 2, 4))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("probe", help="read controller information without changing lighting")
    color_parser = sub.add_parser("set", help="apply static RGB once and close")
    color_parser.add_argument("--color", required=True, type=parse_color)
    selectors = color_parser.add_mutually_exclusive_group(required=True)
    selectors.add_argument("--header", choices=HEADERS)
    selectors.add_argument("--all-headers", action="store_true", help="test all four external RGB headers")
    selectors.add_argument("--slot", type=int, choices=RGB_SLOTS, help="test one RGB bank by protocol index (0..7)")
    selectors.add_argument("--all-slots", action="store_true", help="test all eight RGB banks, including motherboard lighting")
    color_parser.add_argument("--dry-run", action="store_true", help="show packets without opening the device")
    args = parser.parse_args(argv)
    controller = discover_controller()
    print(f"target: {BOARD_NAME}; ITE 048d:5702 interface 00; {controller.node}; USB {controller.usb.name}", flush=True)
    reports = []
    if args.action == "set":
        if args.all_slots:
            slots = list(RGB_SLOTS)
        elif args.slot is not None:
            slots = [args.slot]
        else:
            slots = list(HEADERS.values()) if args.all_headers else [HEADERS[args.header]]
        reports = static_slot_reports(slots, args.color)
        print("RGB slots: " + ", ".join(str(s) for s in slots) + " (physical fan mapping unverified)", flush=True)
        if any(slot in (5, 6) for slot in slots):
            print("ARGB mode selection enables hardware effects on both D_LED headers.", flush=True)
        if args.dry_run:
            for packet in reports:
                print("planned tx: " + packet.hex(" "))
            return 0
        require_rgb_apps_absent()
    try:
        fd = os.open(controller.node, os.O_RDWR | os.O_CLOEXEC)
    except PermissionError as exc:
        raise RuntimeError("RGB controller access requires root; run this command with sudo") from exc
    try:
        validate_opened_device(fd)
        info = query_info(fd, trace=trace)
        print(json.dumps(info, indent=2), flush=True)
        if args.action == "set":
            validate_info(info)
            for packet in reports:
                send_feature(fd, packet, trace=trace)
                time.sleep(0.05)
            print("Static RGB reports accepted; check which fans changed color. No flash save requested.")
    finally:
        os.close(fd)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
