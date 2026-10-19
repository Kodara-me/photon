"""G502 X PLUS HID++ RGB discovery and static-color operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .rgb import (
    RgbCapabilities,
    discover_rgb_features,
    discover_capabilities as discover_rgb_capabilities,
)
from .hidpp import FeatureInfo, HidppClient
from .probe import probe_dict

G502_VENDOR_ID = "046d"
G502_PRODUCT_ID = "c095"
G502_RECEIVER_PRODUCT_ID = "c547"


@dataclass(frozen=True)
class G502Probe:
    path: str
    interface: dict[str, Any]
    device_index: int = 0xFF
    transport: str = "direct"
    root: FeatureInfo | None = None
    features: tuple[FeatureInfo, ...] = ()
    capabilities: RgbCapabilities | None = None
    status: str = "unknown"
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        result = probe_dict(self.path, self.interface, self.status, self.error, self.root, self.features)
        result["device_index"] = self.device_index
        result["transport"] = self.transport
        if self.capabilities is not None:
            result["capabilities"] = self.capabilities.as_dict()
        return result


def discover_capabilities(client: HidppClient, features: list[FeatureInfo]) -> RgbCapabilities:
    return discover_rgb_capabilities(client, features)


def prepare_rgb_effects(client: HidppClient, capabilities: RgbCapabilities) -> None:
    """Arm the G502 X PLUS effect engine before a zone write.

    This is a G502-specific SetEffectByIndex preparation packet. The device
    reports one RGB effect entry, so the preparation selects effect count 1.
    """
    if capabilities.feature.feature_id != 0x8071:
        return
    payload = b"\xff" + bytes([len(capabilities.zones)]) + b"\x00" * 10 + b"\x01"
    client.feature_request(capabilities.feature.index, 0x10, payload)


def claim_rgb_control(client: HidppClient, capabilities: RgbCapabilities) -> None:
    """Claim host RGB control for the G502 effect engine."""
    if capabilities.feature.feature_id == 0x8071:
        # SetSWControl(set=1, mode=3, flags=NVCONFIG): the G502-specific
        # effect engine rejects writes until this host claim is active.
        client.feature_request(capabilities.feature.index, 0x50, b"\x01\x03\x04")


def set_g502_perkey_color(
    client: HidppClient,
    features: tuple[FeatureInfo, ...],
    color: tuple[int, int, int],
    zone_ids: tuple[int, ...] = tuple(range(1, 9)),
) -> None:
    """Paint the G502 X PLUS's eight 0x8081 LED addresses and commit them."""
    feature = next((item for item in features if item.feature_id == 0x8081), None)
    if feature is None:
        raise ValueError("G502 does not expose PER_KEY_LIGHTING_V2")
    r, g, b = color
    client.feature_request(feature.index, 0x60, bytes([r, g, b]) + bytes(zone_ids))
    client.feature_request(feature.index, 0x70, b"\x00\x00\x00\x00\x00")
