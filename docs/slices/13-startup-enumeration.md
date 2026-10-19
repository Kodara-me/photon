# Slice 13 — apply at startup

## Objective

Apply configuration to devices already present when a user service starts.

## Scope

Enumerate current devices, probe readiness, apply once per supported physical device, log failures, and exit or hand control to the later monitor mode.

## Non-goals

Do not solve hotplug yet and do not poll continuously.

## Verification

Start with each device connected, with one device absent, and with a device present but not yet ready.

## Done when

Login/startup behavior is correct without depending on historical udev events.

