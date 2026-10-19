# Slice 5 — query RGB capabilities

## Objective

Determine the G733 RGB zone/effect model.

## Scope

Using the discovered feature, query version, zone count, zone identifiers, current effect/color state, and supported static-color operation where available.

## Non-goals

Do not change more than necessary to query state. Do not implement animation support.

## Verification

Compare returned zone information with the physical headset and document any left/right or front-zone mapping.

## Done when

The required static-color command can be designed from observed capability data.

## Implementation status

Implemented in [`photon/g733.py`](../../photon/g733.py) and exposed by [`tools/photon_g733_discover.py`](../../tools/photon_g733_discover.py). The implementation supports the capability-query paths for `COLOR_LED_EFFECTS (0x8070)` and `RGB_EFFECTS (0x8071)` and reports runtime zone/effect data.

The actual G733 feature choice, zone count, and physical zone mapping remain unverified until the real hidraw node is accessible.
