"""Unified command-line controller for Photon."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from photon import __version__


DEVICE_COMMANDS: dict[str, str] = {
    "g733": "G733 Gaming Headset",
    "g502": "G502 X PLUS",
    "keyboard": "PRO Gaming Keyboard",
    "ram": "Corsair Vengeance RGB DDR5",
    "motherboard": "Gigabyte motherboard and fan RGB (all eight slots)",
}


def _add_color_options(parser: argparse.ArgumentParser, *, zones: bool) -> None:
    parser.add_argument("--color", help="static color as #RRGGBB; defaults to configuration")
    parser.add_argument("--config", help="TOML configuration path")
    if zones:
        group = parser.add_mutually_exclusive_group()
        group.add_argument("--zone", type=int, help="one discovered zone index")
        group.add_argument("--all", action="store_true", help="apply to every discovered zone")
    parser.add_argument("--trace", action="store_true", help="show protocol traffic")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="photon", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subcommands = parser.add_subparsers(dest="command", required=True)

    apply = subcommands.add_parser("apply", help="apply one color to all available devices")
    _add_color_options(apply, zones=False)
    apply.add_argument("--only", choices=DEVICE_COMMANDS, help="apply only one device type")

    monitor = subcommands.add_parser("monitor", help="apply at startup and monitor supported device arrivals")
    monitor.add_argument("--config", help="TOML configuration path")

    service = subcommands.add_parser("service", help="install or manage the system service")
    service.add_argument("action", choices=("install", "uninstall", "status", "restart", "check"))

    probe = subcommands.add_parser("probe", help="perform a read-only device probe")
    probe_subcommands = probe.add_subparsers(dest="probe_device", required=True)
    ram_probe = probe_subcommands.add_parser("ram", help="probe Corsair RAM controllers")
    ram_probe.add_argument("--json", action="store_true", dest="as_json")
    g502_probe = probe_subcommands.add_parser("g502", help="probe G502 USB or receiver paths without RGB writes")
    g502_probe.add_argument("--json", action="store_true", dest="as_json")
    g502_probe.add_argument("--trace", action="store_true", help="show HID++ discovery traffic")
    g733_events = probe_subcommands.add_parser("g733-events", help="capture G733 reports without RGB writes")
    g733_events.add_argument("--seconds", type=float, default=30.0, help="capture duration; defaults to 30 seconds")
    g733_features = probe_subcommands.add_parser("g733", help="look up G733 reconnect-related feature indexes")
    g733_features.add_argument("--json", action="store_true", dest="as_json")
    motherboard_probe = probe_subcommands.add_parser("motherboard", help="query the verified ITE RGB controller")
    motherboard_probe.add_argument("--json", action="store_true", dest="as_json")
    motherboard_probe.add_argument("--trace", action="store_true")

    for device, label in DEVICE_COMMANDS.items():
        device_parser = subcommands.add_parser(device, help=f"apply a color to {label}")
        _add_color_options(device_parser, zones=device not in {"ram", "motherboard"})
    return parser


def _forward_color_options(args: argparse.Namespace, *, zones: bool) -> list[str]:
    forwarded: list[str] = []
    if args.color is not None:
        forwarded.extend(("--color", args.color))
    if args.config is not None:
        forwarded.extend(("--config", args.config))
    if zones and args.zone is not None:
        forwarded.extend(("--zone", str(args.zone)))
    elif zones and args.all:
        forwarded.append("--all")
    if args.trace:
        forwarded.append("--trace")
    return forwarded


def _device_main(device: str) -> Callable[[list[str] | None], int]:
    if device == "g733":
        from tools.photon_g733_color import main
    elif device == "g502":
        from tools.photon_g502_color import main
    elif device == "keyboard":
        from tools.photon_keyboard_color import main
    elif device == "ram":
        from tools.photon_ram_color import main
    elif device == "motherboard":
        from tools.photon_motherboard import main
    else:  # argparse prevents this; retain a useful error for API callers.
        raise ValueError(f"unsupported device command: {device}")
    return main


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "monitor":
        from photon.monitor import main as monitor_main

        forwarded = []
        if args.config is not None:
            forwarded.extend(("--config", args.config))
        return monitor_main(forwarded)
    if args.command == "service":
        from photon.service import main as service_main

        return service_main([args.action])
    if args.command == "probe":
        if args.probe_device == "motherboard":
            from tools.photon_motherboard import probe_main

            forwarded = ["--json"] if args.as_json else []
            if args.trace:
                forwarded.append("--trace")
            return probe_main(forwarded)
        if args.probe_device == "ram":
            from tools.photon_ram_probe import main as probe_main

            return probe_main(["--json"] if args.as_json else [])
        if args.probe_device == "g733-events":
            from tools.photon_g733_events import main as probe_main

            return probe_main(["--seconds", str(args.seconds)])
        if args.probe_device == "g733":
            from tools.photon_g733_features import main as probe_main

            return probe_main(["--json"] if args.as_json else [])
        from tools.photon_g502_probe import main as probe_main

        forwarded = ["--json"] if args.as_json else []
        if args.trace:
            forwarded.append("--trace")
        return probe_main(forwarded)
    if args.command in DEVICE_COMMANDS:
        return _device_main(args.command)(
            _forward_color_options(args, zones=args.command not in {"ram", "motherboard"})
        )
    if args.only:
        return _device_main(args.only)(
            # ``apply`` intentionally has no zone selector. Targeted device
            # commands use their own default (all discovered zones).
            _forward_color_options(args, zones=False)
        )
    from tools.photon_apply import main as apply_main

    return apply_main(_forward_color_options(args, zones=False))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
