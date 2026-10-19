#!/usr/bin/env python3
"""Apply one configured static color to every available supported device."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from dataclasses import dataclass
from collections.abc import Callable

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from photon.config import DEFAULT_CONFIG_PATH, format_color, resolve_color
from photon.corsair_ram import discover_modules, set_module_color, static_color_packet
from photon.g502_x_plus import claim_rgb_control, prepare_rgb_effects, set_g502_perkey_color
from photon.g733 import discover_capabilities as discover_g733_capabilities
from photon.g733 import discover_rgb_features, set_zone_color
from photon.hid_transport import HidTransport
from photon.hidpp import HidppClient
from photon.pro_keyboard import claim_led_control
from photon.gigabyte_rgb import apply_static_color as apply_motherboard_color
from tools.photon_g502_probe import probe_interfaces as probe_g502_interfaces, select_unique_rgb_probe
from tools.photon_hidpp_query import _g733_path
from tools.photon_keyboard_color import select_keyboard_probe
from tools.photon_keyboard_probe import probe_interfaces as probe_keyboard_interfaces


@dataclass(frozen=True)
class ApplyResult:
    """The targets applied and failures observed during one bounded apply pass."""

    applied: tuple[str, ...]
    failures: tuple[str, ...]


def _trace(enabled: bool):
    if not enabled:
        return None
    return lambda direction, data: print(f"{direction}: {data.hex(' ')}", file=sys.stderr)


def _apply_g733(color, trace_enabled: bool) -> str:
    path = _g733_path()
    with HidTransport().open_session(path) as session:
        client = HidppClient(session, force_long_reports=True, trace=_trace(trace_enabled))
        capabilities = discover_g733_capabilities(client, discover_rgb_features(client))
        for zone in capabilities.zones:
            set_zone_color(client, capabilities, zone.index, color)
    return f"G733 ({len(capabilities.zones)} zone(s))"


def _apply_g502(color, trace_enabled: bool) -> str:
    probe = select_unique_rgb_probe(probe_g502_interfaces(trace=trace_enabled))
    if probe.capabilities is None:
        raise RuntimeError("selected G502 interface has no RGB capabilities")
    with HidTransport().open_session(probe.path) as session:
        client = HidppClient(
            session,
            device_index=probe.device_index,
            force_long_reports=True,
            trace=_trace(trace_enabled),
        )
        claim_rgb_control(client, probe.capabilities)
        prepare_rgb_effects(client, probe.capabilities)
        for zone in probe.capabilities.zones:
            set_zone_color(client, probe.capabilities, zone.index, color)
        set_g502_perkey_color(client, probe.features, color)
    return f"G502 X PLUS ({len(probe.capabilities.zones)} zone(s) + LEDs)"


def _apply_keyboard(color, trace_enabled: bool) -> str:
    probe = select_keyboard_probe(probe_keyboard_interfaces(trace=trace_enabled))
    if probe.capabilities is None:
        raise RuntimeError("selected keyboard interface has no RGB capabilities")
    with HidTransport().open_session(probe.path) as session:
        client = HidppClient(session, force_long_reports=True, trace=_trace(trace_enabled))
        claim_led_control(client, probe.capabilities)
        for zone in probe.capabilities.zones:
            set_zone_color(client, probe.capabilities, zone.index, color)
    return f"PRO Gaming Keyboard ({len(probe.capabilities.zones)} zone(s))"


def _apply_ram(color, trace_enabled: bool) -> list[str]:
    modules = discover_modules()
    for module in modules:
        set_module_color(module, color)
        if trace_enabled:
            print(
                f"RAM {module.bus_path} SPD 0x{module.spd_address:02x} "
                f"controller 0x{module.controller_address:02x} tx: "
                f"31 {static_color_packet(color).hex(' ')}",
                file=sys.stderr,
            )
    return [module.name for module in modules]


def _apply_motherboard(color, trace_enabled: bool) -> str:
    apply_motherboard_color(color, trace=_trace(trace_enabled))
    return "Gigabyte motherboard/fan RGB (8 slots)"


def apply_available(
    color: tuple[int, int, int],
    *,
    trace_enabled: bool = False,
    only: str | None = None,
) -> ApplyResult:
    """Apply a color to available targets without allowing one failure to abort others."""
    operations: tuple[tuple[str, str, Callable[[], str | list[str]]], ...] = (
        ("g733", "G733", lambda: _apply_g733(color, trace_enabled)),
        ("g502", "G502 X PLUS", lambda: _apply_g502(color, trace_enabled)),
        ("keyboard", "PRO Gaming Keyboard", lambda: _apply_keyboard(color, trace_enabled)),
        ("ram", "Corsair RAM", lambda: _apply_ram(color, trace_enabled)),
        ("motherboard", "Gigabyte motherboard RGB", lambda: _apply_motherboard(color, trace_enabled)),
    )
    if only is not None and only not in {key for key, _, _ in operations}:
        raise ValueError(f"unsupported apply target: {only}")

    applied: list[str] = []
    failures: list[str] = []
    for key, label, operation in operations:
        if only is not None and key != only:
            continue
        try:
            result = operation()
            applied.extend(result if isinstance(result, list) else [result])
        except Exception as exc:
            failures.append(f"{label}: {exc}")
    return ApplyResult(tuple(applied), tuple(failures))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--color", help="static color as #RRGGBB; defaults to configuration")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="TOML configuration path")
    parser.add_argument("--trace", action="store_true")
    args = parser.parse_args(argv)
    color = resolve_color(args.color, args.config)

    result = apply_available(color, trace_enabled=args.trace)

    print(f"applied {format_color(color)} to {len(result.applied)} device target(s)")
    for failure in result.failures:
        print(f"unavailable: {failure}", file=sys.stderr)
    return 0 if result.applied else 1


if __name__ == "__main__":
    raise SystemExit(main())
