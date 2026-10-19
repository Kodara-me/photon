# Slice 9 — apply G502 X PLUS static RGB

## Objective

Implement the minimum device-specific operation needed to set the G502 X PLUS static color.

## Scope

Add only the confirmed feature, zone mapping, report format, and any device-specific quirk discovered in Slice 8.

## Non-goals

Do not generalize to every G502 model or add animation support.

## Verification

Test direct USB, repeated application, device removal, and unsupported-feature responses.

## Done when

The exact current G502 X PLUS can be controlled without relying on OpenRGB.

## Implementation status

Implemented by [`tools/photon_g502_color.py`](../../tools/photon_g502_color.py). The command re-probes the G502, requires exactly one RGB-capable interface, requires an advertised static effect, and applies a requested color to one selected zone or all discovered zones before closing the session.

The G502 `RGB_EFFECTS` write uses function `0x10` with payload `zone + effect-list index + ten effect-parameter bytes + 0x01`. The target-machine trace confirms one discovered zone; its sole effect-list entry is index `0`, representing static effect `0x01`.

The physical color change remains to be verified on the target machine. No G502 RGB write has completed in the current execution environment because its hidraw nodes are unavailable.
