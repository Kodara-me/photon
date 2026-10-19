#!/usr/bin/env python3
"""Probe exact Corsair Vengeance DDR5 RGB modules without writing RGB state."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.corsair_ram import discover_modules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    modules = discover_modules()
    result = {
        "modules": [
            {
                "bus": module.bus_path,
                "spd_address": f"0x{module.spd_address:02x}",
                "controller_address": f"0x{module.controller_address:02x}",
                "part_number": module.part_number,
                "led_count": module.led_count,
            }
            for module in modules
        ]
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else f"found {len(modules)} matching Corsair RAM module(s)")
    return 0 if modules else 1


if __name__ == "__main__":
    raise SystemExit(main())
