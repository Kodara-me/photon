#!/usr/bin/env python3
"""Capture raw G733 HID reports without sending any device command."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.hid_transport import HidTransport
from tools.photon_hidpp_query import _g733_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=30.0, help="capture duration; defaults to 30 seconds")
    args = parser.parse_args(argv)
    if args.seconds <= 0:
        raise ValueError("--seconds must be positive")

    deadline = time.monotonic() + args.seconds
    reports = 0
    print(f"listening on {_g733_path()} for up to {args.seconds:g} seconds", file=sys.stderr)
    with HidTransport().open_session(_g733_path()) as session:
        while True:
            remaining_ms = int((deadline - time.monotonic()) * 1000)
            if remaining_ms <= 0:
                break
            report = session.read_report(timeout_ms=min(1000, remaining_ms))
            if report:
                reports += 1
                print(f"{time.monotonic():.3f} {report.hex(' ')}")
    print(f"captured {reports} report(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
