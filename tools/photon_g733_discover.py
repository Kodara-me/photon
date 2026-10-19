#!/usr/bin/env python3
"""Discover the current G733 HID++ RGB features and capabilities."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.g733 import G733_PRODUCT_ID, G733_VENDOR_ID, discover_capabilities, discover_rgb_features
from photon.hid_transport import HidTransport
from photon.hidpp import HidppClient, HidppError
from tools.photon_hidpp_query import _g733_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    trace = (lambda direction, data: print(f"{direction}: {data.hex(' ')}", file=sys.stderr)) if args.trace else None
    with HidTransport().open_session(_g733_path()) as session:
        client = HidppClient(session, force_long_reports=True, trace=trace)
        features = discover_rgb_features(client)
        capabilities = discover_capabilities(client, features)
    result = {"features": [feature.__dict__ for feature in features], "capabilities": capabilities.as_dict()}
    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HidppError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
