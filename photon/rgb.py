"""Shared HID++ RGB discovery and static-color operations."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .hidpp import FeatureInfo, HidppClient

COLOR_LED_EFFECTS = 0x8070
RGB_EFFECTS = 0x8071
PER_KEY_LIGHTING_V2 = 0x8081
FEATURE_CANDIDATES = (COLOR_LED_EFFECTS, RGB_EFFECTS, PER_KEY_LIGHTING_V2)


@dataclass(frozen=True)
class Zone:
    index: int
    location: int
    effect_count: int
    effect_ids: tuple[int, ...]

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class RgbCapabilities:
    feature: FeatureInfo
    zone_count: int
    readable: bool
    capabilities: int
    zones: tuple[Zone, ...]

    def as_dict(self):
        return {
            "feature": asdict(self.feature),
            "zone_count": self.zone_count,
            "readable": self.readable,
            "capabilities": self.capabilities,
            "zones": [zone.as_dict() for zone in self.zones],
        }


def discover_rgb_features(client: HidppClient) -> list[FeatureInfo]:
    return client.discover_features(FEATURE_CANDIDATES)


def _discover_color_led_effects(client: HidppClient, feature: FeatureInfo) -> RgbCapabilities:
    info = client.feature_request(feature.index, 0).payload
    if len(info) < 5:
        raise ValueError("short COLOR_LED_EFFECTS information response")
    zone_count = info[0]
    capabilities = int.from_bytes(info[3:5], "big")
    zones: list[Zone] = []
    for zone_index in range(zone_count):
        zone_info = client.feature_request(feature.index, 0x10, bytes([zone_index, 0xFF, 0x00])).payload
        if len(zone_info) < 4:
            raise ValueError(f"short LED zone response for zone index {zone_index}")
        location = int.from_bytes(zone_info[1:3], "big")
        effect_count = zone_info[3]
        effect_ids: list[int] = []
        for effect_index in range(effect_count):
            effect_info = client.feature_request(feature.index, 0x20, bytes([zone_index, effect_index, 0])).payload
            if len(effect_info) < 4:
                raise ValueError(f"short LED effect response for zone index {zone_index}")
            effect_ids.append(int.from_bytes(effect_info[2:4], "big"))
        zones.append(Zone(zone_index, location, effect_count, tuple(effect_ids)))
    return RgbCapabilities(feature, zone_count, bool(capabilities & 1), capabilities, tuple(zones))


def _discover_rgb_effects(client: HidppClient, feature: FeatureInfo) -> RgbCapabilities:
    info = client.feature_request(feature.index, 0, b"\xff\xff\x00").payload
    if len(info) < 7:
        raise ValueError("short RGB_EFFECTS information response")
    zone_count = info[2]
    capabilities = int.from_bytes(info[5:7], "big")
    zones = tuple(Zone(index, 0, 0, (1,)) for index in range(zone_count))
    return RgbCapabilities(feature, zone_count, bool(capabilities & 1), capabilities, zones)


def discover_capabilities(client: HidppClient, features: list[FeatureInfo] | tuple[FeatureInfo, ...]) -> RgbCapabilities:
    for feature in features:
        if feature.feature_id == COLOR_LED_EFFECTS:
            return _discover_color_led_effects(client, feature)
        if feature.feature_id == RGB_EFFECTS:
            return _discover_rgb_effects(client, feature)
    raise ValueError("device exposes no supported RGB feature")


def parse_color(value: str) -> tuple[int, int, int]:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise ValueError("color must be exactly #RRGGBB")
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def static_color_payload(zone: Zone, color: tuple[int, int, int], feature_id: int) -> tuple[int, bytes]:
    if 1 not in zone.effect_ids:
        raise ValueError(f"zone {zone.index} does not advertise static effect 0x01")
    r, g, b = color
    if feature_id == COLOR_LED_EFFECTS:
        effect = bytes([0x01, r, g, b, 0x03, 0, 0, 0, 0, 0, 0])
        return 0x30, bytes([zone.index]) + effect
    if feature_id == RGB_EFFECTS:
        effect_parameters = bytes([r, g, b, 0x02, 0, 0, 0, 0, 0, 0])
        return 0x10, bytes([zone.index, 0x00]) + effect_parameters + b"\x01"
    raise ValueError(f"unsupported RGB feature 0x{feature_id:04x}")


def set_zone_color(client: HidppClient, capabilities: RgbCapabilities, zone_index: int, color: tuple[int, int, int]) -> None:
    zone = next((zone for zone in capabilities.zones if zone.index == zone_index), None)
    if zone is None:
        raise ValueError(f"unknown RGB zone index {zone_index}")
    function, payload = static_color_payload(zone, color, capabilities.feature.feature_id)
    client.feature_request(capabilities.feature.index, function, payload)
