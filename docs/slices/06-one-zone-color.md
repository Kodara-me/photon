# Slice 6 — change one RGB zone

## Objective

Change one confirmed G733 RGB zone to a requested static color from the command line.

## Scope

Implement a single explicit color command using the discovered feature index and confirmed payload format. Use a test color that is visually obvious.

## Non-goals

No daemon, configuration file, animation engine, or multi-device support.

## Verification

Stop Solaar and OpenRGB, run once, observe the physical zone, capture logs/bytes, then close the device.

## Done when

One physical zone changes reliably and the command exits without ongoing traffic.

## Implementation status

Implemented by [`tools/photon_g733_color.py`](../../tools/photon_g733_color.py) with static-effect payload generation in [`photon/g733.py`](../../photon/g733.py). The command requires an explicit `--zone` and `--color '#RRGGBB'`, discovers the feature and capabilities at runtime, writes one zone, and closes.

Physical RGB verification is still pending hardware access. No color write was attempted in this environment.
