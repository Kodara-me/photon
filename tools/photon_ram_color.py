#!/usr/bin/env python3
"""Set every verified Corsair Vengeance DDR5 RGB module to one static color."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.config import DEFAULT_CONFIG_PATH, format_color, resolve_color
from photon.corsair_ram import discover_modules, set_module_color, static_color_packet


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", help="static color as #RRGGBB; defaults to configuration")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="TOML configuration path")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    color = resolve_color(args.color, args.config)
    modules = discover_modules()
    if not modules:
        raise RuntimeError(f"no verified Corsair {format_color(color)} RAM modules found")
    for module in modules:
        set_module_color(module, color)
        if args.trace:
            print(
                f"{module.bus_path} SPD 0x{module.spd_address:02x} "
                f"controller 0x{module.controller_address:02x} tx: "
                f"31 {static_color_packet(color).hex(' ')}",
                file=sys.stderr,
            )
    print(f"applied {format_color(color)} to {len(modules)} Corsair RAM module(s)")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
