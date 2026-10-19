# Slice 1 — enumerate exact devices and interfaces

## Objective

Produce a read-only inspection command that groups hidraw nodes by physical device and reports stable metadata.

## Scope

Use hidapi and/or sysfs/udev to report VID, PID, product, serial, hidraw path, physical USB path, interface number, and report descriptor information where available. Include the currently observed `046d:0afe`, `046d:c095`, and `046d:c339` devices.

## Non-goals

Do not open devices for writes, send HID++ traffic, install packages, or add udev rules.

## Verification

Run with all currently connected devices and confirm mouse/keyboard multi-interface grouping. Confirm that the output does not treat hidraw numbers as persistent identity.

## Done when

Every supported physical device is identified unambiguously and the output is useful as input to later interface selection.

## Implementation status

Implemented in [`tools/photon_enumerate.py`](../../tools/photon_enumerate.py) with unit coverage in [`tests/test_photon_enumerate.py`](../../tests/test_photon_enumerate.py).

The live read-only verification found:

- G733 `046d:0afe`: one hidraw path, current `/dev/hidraw7`, USB path `1-8.2`.
- G502 X PLUS `046d:c095`: three hidraw paths, current `/dev/hidraw2`, `/dev/hidraw3`, and `/dev/hidraw5`, USB path `1-8.4`.
- PRO Gaming Keyboard `046d:c339`: two hidraw paths, current `/dev/hidraw0` and `/dev/hidraw6`, USB path `1-8.3`.

hidapi reports multiple collection records for some shared hidraw paths; the implementation deduplicates those paths and preserves the collection metadata. The tool uses sysfs-backed pyudev lookup so it remains diagnostic-friendly even when a `/dev/hidraw*` node is not visible in the execution environment.
