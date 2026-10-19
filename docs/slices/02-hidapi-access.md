# Slice 2 — verify hidapi access

## Objective

Determine which current hidraw interfaces can be opened by the logged-in user.

## Scope

Enumerate the three target products, open and close each candidate path, and report permission, busy, and transport errors separately.

## Non-goals

Do not send HID++ commands or change RGB. Do not change permissions or udev configuration.

## Verification

Test `hidraw7`, `hidraw2/3/5`, and `hidraw0/6` through metadata-derived paths. Record whether the `lsusb` libusb error has any effect on hidapi.

## Done when

Access behavior is documented and a reliable open/close abstraction exists without depending on numeric hidraw names.

## Implementation status

### Bundle backend correction — 2026-10-02

The pip hidapi distribution exposes `hid` (libusb) and `hidraw` (Linux hidraw).
Enumeration and transport must explicitly import `hidraw`: the code expects real
`/dev/hidraw*` paths, while libusb paths are incompatible with its existence checks
and sysfs association. The previous bundle selected libusb and host service logs
reported missing nodes for G733 and zero RGB-capable mouse/keyboard interfaces,
while RAM applied successfully. The corrected bundle collects `hidraw`, and its
dependency check loads that same backend. A regression test verifies both enumeration
and transport use it. Host RGB application still needs verification after reinstall.

Implemented in [`photon/hid_transport.py`](../../photon/hid_transport.py) and [`tools/photon_access.py`](../../tools/photon_access.py), with transport classification tests in [`tests/test_photon_enumerate.py`](../../tests/test_photon_enumerate.py).

The diagnostic supports both forms:

```bash
python3 tools/photon_access.py
python3 -m tools.photon_access --json
```

The current execution environment enumerates the six supported hidraw paths through hidapi/sysfs but does not expose the corresponding `/dev/hidraw*` nodes. Live Slice 2 output therefore reports `missing_node` for all six paths here. No HID++ reads or writes were performed. Real permission/open behavior still needs to be verified on the host environment where the device nodes are available.
