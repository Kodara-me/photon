# Slice 10 — probe PRO keyboard interfaces

## Objective

Identify the protocol-capable keyboard hidraw interface and its RGB model.

## Scope

Repeat harmless HID++ and feature discovery against `046d:c339` interfaces. Determine whether RGB is exposed through `0x8070`, `0x8071`, `0x8081`, or another mechanism.

## Non-goals

Do not implement per-key lighting until whole-device/static behavior is understood.

## Verification

Record interface, device index, feature version, zone model, and direct USB behavior.

## Done when

The smallest reliable static-color operation is known for the keyboard.

## Implementation status

Implemented by [`tools/photon_keyboard_probe.py`](../../tools/photon_keyboard_probe.py). The probe enumerates every metadata-derived `046d:c339` interface, performs root and candidate feature discovery, queries the known top-level information functions for `0x8070` and `0x8071`, and records per-interface JSON plus optional packet traces. It does not issue RGB writes and does not assume a `0x8081` payload model.

Live probing on the target machine selected `/dev/hidraw6` (USB interface `01`) as the protocol-capable path. `/dev/hidraw0` (interface `00`) did not answer the HID++ Feature Set query. The keyboard resolved `COLOR_LED_EFFECTS (0x8070)` to feature index `0x0d`, version `5`; `RGB_EFFECTS (0x8071)` and `PER_KEY_LIGHTING_V2 (0x8081)` were absent. The `0x8070` information response reported two zones and capability word `0x0007`.

The probe performs the read-only zone/effect queries for `0x8070`. The target machine reports zone 0 at location `1` with effects `0x00, 0x01, 0x0a, 0x03, 0x04, 0x05`, and zone 1 at location `2` with effects `0x00, 0x01, 0x0a, 0x03`; both zones advertise static effect `0x01`.

A guarded write command is implemented by [`tools/photon_keyboard_color.py`](../../tools/photon_keyboard_color.py). It selects the unique protocol interface by metadata/probing, claims host LED control, and applies the requested static color to one or all discovered zones. Physical verification remains pending.
