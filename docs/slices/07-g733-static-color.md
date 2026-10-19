# Slice 7 — apply complete G733 static color

## Objective

Apply one requested static color to every RGB zone required on the G733.

## Scope

Extend the one-zone proof only to the confirmed headset zones. Keep the operation one-shot and command-line driven.

## Non-goals

No resident service, hotplug handling, animation, or configuration reload.

## Verification

Test multiple colors, repeated invocation, headset readiness delay, and device disappearance during access.

## Done when

The G733 first milestone works end-to-end without Solaar or OpenRGB.

## Implementation status

Implemented by the `--all` mode of [`tools/photon_g733_color.py`](../../tools/photon_g733_color.py). It discovers all reported zones and applies the requested color one zone at a time, then closes the device.

The first milestone is not yet physically complete: the current execution environment lacks `/dev/hidraw7`, so live HID++ responses and RGB changes remain to be verified on the host with Solaar and OpenRGB not participating.
