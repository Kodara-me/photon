# Slice 19 — motherboard/fan RGB in the service

## Authorization and behavior

On 2026-10-02 the user requested that the service apply its configured color to
all motherboard RGB slots, following the physically successful eight-slot green test.
This supersedes Slice 18's proposed requirement to identify a single fan slot first.

`photon/gigabyte_rgb.py` now owns the measured controller discovery, information
checks and static-effect packet builder previously used by the standalone experiment.
The experiment imports the same implementation; there is no second protocol copy.
The service and `apply` operation apply the global color to all eight slots once.
`motherboard` and `apply --only motherboard` provide targeted manual application;
`probe motherboard` queries information without changing lighting.

## Readiness and events

Readiness means the controller appears with matching DMI board, USB VID/PID,
interface, HID descriptor and opened device identity, then returns a complete 64-byte
information reply matching the measured product, controller number, firmware,
description and chip ID. No RGB command is sent before that check succeeds.

The existing monitor attempts each startup target independently, with up to four
attempts and delays of 0.5, 1 and 2 seconds. Missing nodes, unavailable information
or failed transfers produce bounded retries and a clear final warning. The process
then waits for events. It also handles ITE `048d:5702` hidraw add events, so a late
controller appearance triggers another bounded attempt. There is no periodic polling.

The udev subscription now explicitly starts before startup application, so arrivals
during initialization are queued. Success logs name the target, including the
motherboard/fan RGB operation.

## Limits

Controller operations use exactly the successful all-slot sequence and packet spacing,
then close the handle. There are no pump/fan speed commands, controller resets,
calibration changes, LED-count writes or flash saves. Existing configuration and
system unit contents are sufficient. Solaar/OpenRGB must be absent during RGB writes.

The known board is Z790 AORUS ELITE AX with USB `048d:5702`, information identifying
IT5701 firmware 3.5.5.0 and chip ID `0x57010100`. Firmware/identity mismatches fail
clearly instead of assuming compatibility. Individual physical slot mapping remains
unknown and is not required for the requested uniform color. Eight-slot green was
confirmed by the user; cold-boot readiness timing and the installed service's physical
result need verification after reinstall/reboot. USB transfer success alone is not
proof of a visible color change.

## Verification

Tests cover the measured response, all-slot packet/mask equivalence, identity/readiness
before RGB writes, handle closure on failed information/transfer, targeted CLI dispatch,
ITE event filtering, late arrival retries, exhausted retries, and subscribing before
startup. All 95 repository tests passed. The one-file Linux bundle rebuilt successfully;
the bundled motherboard apply/probe help and runtime dependency check passed. A bundled
information-probe invocation imported the new backend and reported the unavailable
`/dev/hidraw3` node in the sandbox before any device query. No new RGB commands or
system service installation were run during integration. The user must reinstall the
rebuilt bundle from the host terminal and verify service startup and reboot behavior.
