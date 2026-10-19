"""G733-specific metadata, with shared RGB operations re-exported."""

from .rgb import (
    COLOR_LED_EFFECTS,
    FEATURE_CANDIDATES,
    PER_KEY_LIGHTING_V2,
    RGB_EFFECTS,
    RgbCapabilities,
    Zone,
    _discover_color_led_effects,
    _discover_rgb_effects,
    discover_capabilities,
    discover_rgb_features,
    parse_color,
    set_zone_color,
    static_color_payload,
)

G733_VENDOR_ID = "046d"
G733_PRODUCT_ID = "0afe"

# Kept as a compatibility alias for existing device-specific callers.
G733Capabilities = RgbCapabilities
