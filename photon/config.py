"""Minimal configuration loading for the Photon service."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .rgb import parse_color

DEFAULT_CONFIG_PATH = Path("/etc/photon/config.toml")
DEFAULT_COLOR_HEX = "#8B5CF6"
DEFAULT_COLOR = (0x8B, 0x5C, 0xF6)


class ConfigError(ValueError):
    """Raised when the Photon configuration is missing or invalid."""


@dataclass(frozen=True)
class PhotonConfig:
    color: tuple[int, int, int]


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> PhotonConfig:
    config_path = Path(path)
    try:
        with config_path.open("rb") as config_file:
            raw = tomllib.load(config_file)
    except FileNotFoundError:
        return PhotonConfig(DEFAULT_COLOR)
    except OSError as exc:
        raise ConfigError(f"cannot read configuration file {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"invalid TOML in {config_path}: {exc}") from exc

    unknown = set(raw) - {"color"}
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ConfigError(f"unknown configuration key(s): {names}")
    if "color" not in raw:
        raise ConfigError("configuration requires a color key")
    if not isinstance(raw["color"], str):
        raise ConfigError("color must be a quoted #RRGGBB string")
    try:
        color = parse_color(raw["color"])
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return PhotonConfig(color)


def resolve_color(value: str | None, path: str | Path = DEFAULT_CONFIG_PATH) -> tuple[int, int, int]:
    """Resolve an optional CLI color, falling back to the TOML configuration."""
    if value is not None:
        try:
            return parse_color(value)
        except ValueError as exc:
            raise ConfigError(str(exc)) from exc
    return load_config(path).color


def format_color(color: tuple[int, int, int]) -> str:
    return "#%02X%02X%02X" % color
