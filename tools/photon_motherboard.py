#!/usr/bin/env python3
"""Apply the configured color to all eight verified motherboard/fan RGB slots."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.config import DEFAULT_CONFIG_PATH, format_color, resolve_color
from photon.gigabyte_rgb import apply_static_color, read_controller_info


def _trace(direction: str, data: bytes) -> None:
    print(f"{direction}: {data.hex(' ')}", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", help="static color as #RRGGBB; defaults to configuration")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH))
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    color = resolve_color(args.color, args.config)
    apply_static_color(color, trace=_trace if args.trace else None)
    print(f"applied {format_color(color)} to motherboard/fan RGB (8 slots)")
    return 0


def probe_main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Query motherboard RGB information without changing lighting")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    info = read_controller_info(trace=_trace if args.trace else None)
    if args.as_json:
        print(json.dumps(info, indent=2, sort_keys=True))
    else:
        print(f"{info['board']}: {info['description']}; chip {info['chip_id']}; {info['hidraw']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
