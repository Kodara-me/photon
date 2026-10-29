# Photon project instructions

## Project purpose

Photon is a deliberately small Linux-native RGB service for this specific machine and these Logitech devices. The Logitech devices also work from the command line on Windows (`photon apply`, `g733`, `g502`, `keyboard`, `motherboard`, `ram` and their probes); the Windows-specific choices live in `photon/host.py`, `photon/pawnio.py` and `photon/windows_firmware.py` (the RAM goes through PawnIO, elevated, with the i801 module pinned and checked by `tools/build_bundle.py`), and the Windows service (`photon/windows_service.py`, `photon/windows_monitor.py`) runs as LocalSystem under the Service Control Manager, starts at boot before sign-in and reapplies on resume:

- Logitech G502 X PLUS (`046d:c095`)
- Logitech PRO Gaming Keyboard (`046d:c339`)
- Logitech G733 Gaming Headset (`046d:0afe`)
- 2× Corsair Vengeance RGB DDR5 (`CMH64GX5M2B5600C40`)

The first milestone is a command-line Python program that identifies one actual device and changes its RGB to a requested static color without Solaar or OpenRGB participating.

The complete technical plan is in [`docs/PLAN.md`](docs/PLAN.md). The independently testable work slices are in [`docs/slices/`](docs/slices/).

## Current project status

Every device in the list above, plus the Gigabyte Z790 AORUS ELITE AX RGB controller, has a backend, a read-only probe and tests. The root systemd service, the standalone bundle and its installer are implemented. Each slice document records what was verified on hardware and what remains open.

The machine inspection found these current USB/hidraw mappings:

| Device | VID:PID | Current hidraw nodes |
|---|---|---|
| G733 Gaming Headset | `046d:0afe` | `hidraw7` |
| G502 X PLUS | `046d:c095` | `hidraw2`, `hidraw3`, `hidraw5` |
| PRO Gaming Keyboard | `046d:c339` | `hidraw0`, `hidraw6` |

The hidraw numbers are ephemeral. Never use them as persistent identifiers.

## Non-negotiable constraints

- Do not use C#.
- Prefer Python for the prototype and likely the permanent implementation.
- Do not install packages or alter system configuration without explicit user approval.
- Do not modify Solaar, OpenRGB, CoolerControl, udev rules, or systemd units unless a later task explicitly requests it.
- No GUI, tray icon, web UI, database, plugin system, or general-purpose RGB framework.
- No root daemon unless a concrete technical requirement is demonstrated.
- Prefer a systemd user service and least-privilege hidraw access.
- Prefer event-driven udev/libudev/pyudev handling to periodic polling.
- Do not continuously hammer devices. Apply configuration once, then close the device.
- Do not assume USB interface, PID, HID++ version, feature index, device index, report size, receiver relationship, or RGB protocol. Verify each against hardware.
- Do not blindly copy Solaar or OpenRGB architecture. Use them as protocol references only.
- The Corsair RAM backend uses direct Linux SMBus/I²C access through `i2c-dev`. It must identify
  the kernel-bound DDR5 SPD hub and verify the paired RGB-controller signature before writing.

## Safe development workflow

Work through the slice documents in order. Each slice must have a small, observable result and a clear stopping point. Prefer read-only inspection until a slice explicitly requires a device command. Any command that changes RGB must identify the exact target, record the packet/result, and be run with Solaar and OpenRGB absent unless the slice says otherwise.

Before changing code:

1. Read [`docs/PLAN.md`](docs/PLAN.md) and the relevant slice document.
2. Inspect the current workspace and preserve unrelated user changes.
3. State any hardware or protocol assumption that is not yet verified.
4. Make the smallest change that satisfies the slice.

After changing code:

1. Run the narrowest relevant test or manual verification.
2. Record hardware-dependent observations in the slice document or a dated lab note; do not turn temporary observations into unexplained constants.
3. Check that no system files, services, udev rules, or external applications were changed unintentionally.
4. Report what was verified and what remains unknown.

## Protocol guidance

Implement only the HID++ subset required by the three devices:

- HID report framing and transport
- root/feature discovery
- feature index resolution
- HID++ error decoding
- RGB capability and static-color commands

For the Corsair RAM, implement only the minimum SMBus subset required by the verified DDR5
controller: SPD-hub association, controller signature reads, and the CRC-protected all-ten-LED
static-color packet. Do not scan or write arbitrary SMBus addresses.

Feature IDs such as `0x8070` are not feature indexes. Resolve feature IDs on the device at runtime. Candidate features include `COLOR_LED_EFFECTS (0x8070)`, `RGB_EFFECTS (0x8071)`, and possibly `PER_KEY_LIGHTING_V2 (0x8081)`, but all support must be experimentally verified.

## Structure

The original target layout, kept as a guide; the actual modules live flat in `photon/` and one-shot commands in `tools/`. Keep the implementation small and separable:

```text
photon/
    __main__.py
    config.py
    discovery.py
    hid_transport.py
    hidpp.py
    i2c.py
    corsair_ram.py
    devices/
        g733.py
        g502_x_plus.py
        pro_keyboard.py
```

## Definition of done for the first milestone

The first milestone is complete when a command-line Python program:

- identifies the actual current G733 by metadata/probing rather than hidraw number;
- sends a harmless HID++ discovery sequence;
- resolves the actual RGB feature and feature index;
- changes a confirmed physical RGB zone to a requested static color;
- handles timeout, permission, and unsupported-feature errors clearly;
- exits after the operation;
- works without Solaar or OpenRGB participating.
