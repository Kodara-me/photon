#!/usr/bin/env python3
"""Probe every current G502 X PLUS HID interface without changing RGB."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.g502_x_plus import (
    G502_PRODUCT_ID,
    G502_RECEIVER_PRODUCT_ID,
    G502_VENDOR_ID,
    G502Probe,
    discover_capabilities,
    discover_rgb_features,
)
from photon.g733 import RGB_EFFECTS
from photon.hid_transport import HidTransport, HidTransportError
from photon.hidpp import DEFAULT_DEVICE_INDEX, HidppClient, HidppError
from tools.photon_enumerate import enumerate_devices


RECEIVER_SLOT_INDICES = tuple(range(1, 7))
RECEIVER_QUERY_TIMEOUT_MS = 350


@dataclass(frozen=True)
class ProbeCandidate:
    interface: dict
    device_index: int
    transport: str


def g502_probe_candidates(devices: list[dict] | None = None) -> list[ProbeCandidate]:
    """Return direct G502 interfaces plus verified HID++ receiver slots.

    Receiver slots are candidate addresses only. They become a G502 path only
    after live feature discovery confirms the known G502 feature signature.
    """
    devices = enumerate_devices() if devices is None else devices
    candidates: list[ProbeCandidate] = []
    for device in devices:
        if device["vendor_id"] != G502_VENDOR_ID:
            continue
        if device["product_id"] == G502_PRODUCT_ID:
            candidates.extend(
                ProbeCandidate(interface, DEFAULT_DEVICE_INDEX, "direct") for interface in device["interfaces"]
            )
        elif device["product_id"] == G502_RECEIVER_PRODUCT_ID:
            for interface in device["interfaces"]:
                report_ids = set(interface.get("report_ids") or ())
                # The HID descriptor verifies this is the receiver's vendor
                # HID++ channel; do not assume an interface number.
                if {0x10, 0x11}.issubset(report_ids):
                    candidates.extend(
                        ProbeCandidate(interface, device_index, "receiver")
                        for device_index in RECEIVER_SLOT_INDICES
                    )
    return candidates


def _is_g502_receiver_signature(features) -> bool:
    return {0x8071, 0x8081}.issubset({feature.feature_id for feature in features})


def probe_interfaces(trace: bool = False) -> list[G502Probe]:
    results: list[G502Probe] = []
    transport = HidTransport()
    for candidate in g502_probe_candidates():
        interface = candidate.interface
        path = interface["hidapi_path"]
        trace_fn = (
            lambda direction, data, path=path, device_index=candidate.device_index: print(
                f"{path}[0x{device_index:02x}] {direction}: {data.hex(' ')}", file=sys.stderr
            )
            if trace
            else None
        )
        try:
            with transport.open_session(path) as session:
                client = HidppClient(
                    session,
                    device_index=candidate.device_index,
                    force_long_reports=True,
                    timeout_ms=RECEIVER_QUERY_TIMEOUT_MS if candidate.transport == "receiver" else 1000,
                    trace=trace_fn,
                )
                root = client.get_feature_set_index()
                if root is None:
                    results.append(
                        G502Probe(path, interface, candidate.device_index, candidate.transport, status="no_feature_set")
                    )
                    continue
                features = discover_rgb_features(client)
                if not features:
                    results.append(
                        G502Probe(
                            path, interface, candidate.device_index, candidate.transport, root=root, status="no_rgb_feature"
                        )
                    )
                    continue
                if candidate.transport == "receiver" and not _is_g502_receiver_signature(features):
                    results.append(
                        G502Probe(
                            path,
                            interface,
                            candidate.device_index,
                            candidate.transport,
                            root=root,
                            features=tuple(features),
                            status="receiver_not_g502",
                        )
                    )
                    continue
                capabilities = discover_capabilities(client, features)
                results.append(
                    G502Probe(
                        path,
                        interface,
                        candidate.device_index,
                        candidate.transport,
                        root=root,
                        features=tuple(features),
                        capabilities=capabilities,
                        # RGB_EFFECTS zone writes are supported on devices
                        # whose capability response is not live-readable;
                        # Solaar uses a write-only 0x10 operation for this
                        # feature. A discovered zone is sufficient here.
                        status=(
                            "rgb_capable"
                            if capabilities.zones
                            and (capabilities.readable or capabilities.feature.feature_id == RGB_EFFECTS)
                            else "rgb_not_readable"
                        ),
                    )
                )
        except (HidTransportError, HidppError, OSError, RuntimeError, ValueError) as exc:
            results.append(
                G502Probe(
                    path, interface, candidate.device_index, candidate.transport, status="error", error=str(exc)
                )
            )
    return results


def select_unique_rgb_probe(results: list[G502Probe]) -> G502Probe:
    candidates = [result for result in results if result.status == "rgb_capable"]
    if len(candidates) != 1:
        targets = ", ".join(f"{result.path}[0x{result.device_index:02x}]" for result in candidates) or "none"
        raise RuntimeError(f"expected exactly one RGB-capable G502 interface; found {len(candidates)} ({targets})")
    return candidates[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    results = probe_interfaces(trace=args.trace)
    selected = None
    try:
        selected = select_unique_rgb_probe(results)
    except RuntimeError:
        pass
    payload = {
        "interfaces": [result.as_dict() for result in results],
        "selected_path": selected.path if selected is not None else None,
        "selected_device_index": selected.device_index if selected is not None else None,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if selected is not None else 1


if __name__ == "__main__":
    raise SystemExit(main())
