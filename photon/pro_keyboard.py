"""PRO Gaming Keyboard HID++ feature probing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rgb import (
    COLOR_LED_EFFECTS,
    FEATURE_CANDIDATES,
    RGB_EFFECTS,
    RgbCapabilities,
    _discover_color_led_effects,
)
from .hidpp import HidppClient
from .hidpp import FeatureInfo
from .probe import probe_dict

PRO_KEYBOARD_VENDOR_ID = "046d"
PRO_KEYBOARD_PRODUCT_ID = "c339"


@dataclass(frozen=True)
class KeyboardProbe:
    path: str
    interface: dict[str, Any]
    root: FeatureInfo | None = None
    features: tuple[FeatureInfo, ...] = ()
    information: dict[str, str] | None = None
    capabilities: RgbCapabilities | None = None
    status: str = "unknown"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = probe_dict(
            self.path,
            self.interface,
            self.status,
            self.error,
            self.root,
            self.features,
        )
        result.update({
            "information": self.information,
            "capabilities": self.capabilities.as_dict() if self.capabilities is not None else None,
        })
        return result


def candidate_features() -> tuple[int, ...]:
    return FEATURE_CANDIDATES


def information_request(feature: FeatureInfo) -> tuple[int, bytes] | None:
    if feature.feature_id == COLOR_LED_EFFECTS:
        return 0, b""
    if feature.feature_id == RGB_EFFECTS:
        return 0, b"\xff\xff\x00"
    # PER_KEY_LIGHTING_V2 has no generic capability query assumed here.
    return None


def discover_capabilities(client: HidppClient, features: tuple[FeatureInfo, ...]) -> RgbCapabilities | None:
    feature = next((item for item in features if item.feature_id == COLOR_LED_EFFECTS), None)
    if feature is None:
        return None
    return _discover_color_led_effects(client, feature)


def claim_led_control(client: HidppClient, capabilities: RgbCapabilities) -> None:
    """Put COLOR_LED_EFFECTS into host-control mode before a write."""
    client.feature_request(capabilities.feature.index, 0x80, b"\x01")
