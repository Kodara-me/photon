#!/usr/bin/env python3
"""Probe every current PRO Gaming Keyboard HID interface read-only."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.hid_transport import HidTransport, HidTransportError
from photon.hidpp import HidppClient, HidppError
from photon.pro_keyboard import (
    PRO_KEYBOARD_PRODUCT_ID,
    PRO_KEYBOARD_VENDOR_ID,
    KeyboardProbe,
    candidate_features,
    discover_capabilities,
    information_request,
)
from tools.photon_enumerate import enumerate_devices


def keyboard_interfaces() -> list[dict]:
    return [
        interface
        for device in enumerate_devices()
        if device["vendor_id"] == PRO_KEYBOARD_VENDOR_ID
        and device["product_id"] == PRO_KEYBOARD_PRODUCT_ID
        for interface in device["interfaces"]
    ]


def probe_interfaces(trace: bool = False) -> list[KeyboardProbe]:
    results: list[KeyboardProbe] = []
    transport = HidTransport()
    for interface in keyboard_interfaces():
        path = interface["hidapi_path"]
        trace_fn = (
            lambda direction, data, path=path: print(
                f"{path} {direction}: {data.hex(' ')}", file=sys.stderr
            )
            if trace
            else None
        )
        try:
            with transport.open_session(path) as session:
                client = HidppClient(session, force_long_reports=True, trace=trace_fn)
                root = client.get_feature_set_index()
                if root is None:
                    results.append(KeyboardProbe(path, interface, status="no_feature_set"))
                    continue
                features = tuple(client.discover_features(candidate_features()))
                information: dict[str, str] = {}
                for feature in features:
                    request = information_request(feature)
                    if request is None:
                        continue
                    function, params = request
                    response = client.feature_request(feature.index, function, params)
                    information[f"0x{feature.feature_id:04x}"] = response.payload.hex(" ")
                capabilities = discover_capabilities(client, features)
                status = "rgb_feature_found" if features else "no_rgb_feature"
                results.append(
                    KeyboardProbe(
                        path,
                        interface,
                        root=root,
                        features=features,
                        information=information,
                        capabilities=capabilities,
                        status=status,
                    )
                )
        except (HidTransportError, HidppError, OSError, RuntimeError, ValueError) as exc:
            results.append(KeyboardProbe(path, interface, status="error", error=str(exc)))
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    results = probe_interfaces(trace=args.trace)
    print(json.dumps({"interfaces": [result.as_dict() for result in results]}, indent=2, sort_keys=True))
    return 0 if any(result.status == "rgb_feature_found" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
