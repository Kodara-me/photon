#!/usr/bin/env python3
"""Set a confirmed G502 X PLUS RGB zone to a static color."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.config import DEFAULT_CONFIG_PATH, format_color, resolve_color
from photon.g733 import set_zone_color
from photon.g502_x_plus import claim_rgb_control, prepare_rgb_effects, set_g502_perkey_color
from photon.hid_transport import HidTransport
from photon.hidpp import HidppClient, HidppError
from tools.photon_g502_probe import probe_interfaces, select_unique_rgb_probe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", help="static color as #RRGGBB; defaults to configuration")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="TOML configuration path")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--zone", type=int, help="one discovered zone index")
    group.add_argument("--all", action="store_true", help="apply to every discovered zone")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)

    color = resolve_color(args.color, args.config)
    probe = select_unique_rgb_probe(probe_interfaces(trace=args.trace))
    capabilities = probe.capabilities
    if capabilities is None:
        raise RuntimeError("selected G502 interface has no RGB capabilities")
    zones = [zone.index for zone in capabilities.zones] if args.all or args.zone is None else [args.zone]
    trace = (
        lambda direction, data: print(f"{direction}: {data.hex(' ')}", file=sys.stderr)
        if args.trace
        else None
    )
    with HidTransport().open_session(probe.path) as session:
        client = HidppClient(session, device_index=probe.device_index, force_long_reports=True, trace=trace)
        claim_rgb_control(client, capabilities)
        prepare_rgb_effects(client, capabilities)
        for zone in zones:
            set_zone_color(client, capabilities, zone, color)
        set_g502_perkey_color(client, probe.features, color)
    print(f"applied {format_color(color)} to {len(zones)} G502 zone(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (HidppError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
