# Photon technical implementation plan

## Status and scope

This is a planning document. No implementation, package installation, service change, udev change, Solaar change, or OpenRGB change is authorized by this document.

Photon is a machine-specific, Linux-native RGB control service for the following Logitech hardware:

| Device | VID:PID | Current interfaces observed |
|---|---|---|
| Logitech G733 Gaming Headset | `046d:0afe` | `hidraw7` |
| Logitech G502 X PLUS | `046d:c095` | `hidraw2`, `hidraw3`, `hidraw5` |
| Logitech PRO Gaming Keyboard | `046d:c339` | `hidraw0`, `hidraw6` |
| Corsair Vengeance RGB DDR5 | `CMH64GX5M2B5600C40` | 2 × 32 GiB; SPD hubs `0x51`, `0x53`; RGB controllers `0x19`, `0x1b` on the Intel SMBus |
| Gigabyte motherboard/fan RGB | Z790 AORUS ELITE AX; USB `048d:5702` | IT5701 firmware 3.5.5.0; all eight RGB effect slots, physically verified with green |

The hidraw numbers are not stable identifiers. Current topology is direct USB from the host; no Logitech receiver was visible during inspection. `lsusb` failed with libusb error `-99`, so sysfs/udev findings should be treated as authoritative for current enumeration while libusb behavior remains an implementation risk.

## Recommended language

Use Python initially and likely permanently. HID traffic is infrequent, and simplicity, protocol experimentation, pyudev integration, and maintainability matter more than runtime performance. Use a thin hidapi binding and avoid a large HID++ framework unless it demonstrably reduces code without hiding device-specific behavior.

C++ offers packaging and dependency advantages but no meaningful runtime advantage here. A later rewrite should only be considered if Python packaging or startup behavior becomes a real problem.

## Protocol strategy

Treat HID report type, HID++ device index, feature ID, feature index, and function/sub-ID as separate values. Do not hard-code a feature index. For each device:

1. Open a candidate hidraw interface.
2. Send a harmless HID++ root query.
3. Confirm a valid response and report framing.
4. Resolve candidate RGB feature IDs at runtime.
5. Query feature version, zones, and capabilities.
6. Change one confirmed RGB zone.
7. Expand to all required zones only after physical verification.

Candidate features are `COLOR_LED_EFFECTS (0x8070)`, `RGB_EFFECTS (0x8071)`, and possibly `PER_KEY_LIGHTING_V2 (0x8081)`. Solaar documents `0x8070` and `0x8071` as supported features, but this is not proof for this hardware or firmware. OpenRGB and Solaar should be used for packet and quirk references only, not copied wholesale.

The Corsair RAM is not a HID++ device. It is controlled through the Intel I801 SMBus using the
kernel-bound DDR5 `spd5118` hubs. The implementation must resolve the current bus from sysfs,
pair each SPD address with its controller, verify controller registers `0x43=0x1b` and
`0x44=0x04`, and then use the proven CRC-protected 32-byte static-color packet. The two current
modules have ten LEDs each and receive one all-LED packet per module.

The motherboard/fan backend uses the measured ITE HID feature-report interface,
checks DMI/USB/descriptor and controller-information identity before writing, then
applies the shared color to all eight RGB slots once and closes. Its packet framing,
firmware identity and physical verification are recorded in Slices 18–19. The service
includes this target in bounded startup retries and monitors its hidraw add events.
It does not control fan speeds, change calibration or write flash.

The G733 is the proposed first candidate. The G502 X PLUS is the highest-risk device because existing OpenRGB history indicates wired/direct compatibility issues. The keyboard may expose whole-device effects, zones, or per-key lighting; this must be measured.

## Architecture

Keep the eventual implementation to a few small modules:

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

`hid_transport.py` wraps hidapi enumeration, open/read/write, timeout, close, and error normalization. `hidpp.py` implements only report framing, request/response matching, root feature discovery, feature-index lookup, error decoding, and the RGB operations required by these devices. Device modules contain product matching, candidate interface rules, device-index quirks, zone mappings, and RGB command generation.

`python3 -m photon` is the single command-line controller. Its `apply` command applies the
global configured/default color to every available device; device subcommands retain targeted
diagnostic control. This entry point is the future PyInstaller target.

Build a deployable one-file executable with `python3 tools/build_bundle.py`. The build creates an
isolated `build/venv`, installs the pinned build and runtime dependencies, collects
the Linux `hidraw` binding and `pyudev`, and writes `dist/photon`.

The root-owned system service enumerates devices already present at startup, then monitors `hidraw` udev add events internally. It filters supported VID/PID/product metadata, debounces duplicate interface events, retries briefly if initialization is incomplete, applies once, closes the device, and remains idle. RAM is applied during startup because it does not generate `hidraw` events.

Use a minimal TOML or similarly small configuration. A future configuration needs only one color/effect per supported device. Default logging should be silent on success, with concise errors and optional hex-packet debug output.

## Permissions and integration

The system service runs as root because the RAM backend requires direct SMBus access. It also has access to the selected `/dev/hidraw` node, so Photon does not install udev permission rules. Device-arrival handling stays inside the process rather than spawning a privileged action for every udev event.

Build with `python3 tools/build_bundle.py`, then install with `sudo dist/photon service install`. The command installs the executable under `/usr/local/lib/photon`, exposes it as `/usr/local/bin/photon`, and configures the boot-time root systemd unit to execute that global command. It preserves `/etc/photon/config.toml` across uninstall/reinstall.

## Risks and unknowns

Still requiring hardware experiments:

- protocol-capable interface among the mouse and keyboard hidraw nodes;
- direct USB versus receiver-like behavior of the G733 node;
- HID++ report lengths, report IDs, device indexes, and feature versions;
- actual RGB feature and feature index for every device;
- zone numbering and static-color payloads;
- G502 X PLUS wired RGB support;
- keyboard whole-device versus per-key operation;
- readiness and event behavior after wireless wake/reconnect;
- coexistence behavior with Solaar/OpenRGB;
- effect of the current `lsusb` libusb initialization failure.

## First milestone

From a command-line Python program, identify the actual current G733 device and reliably change its RGB to a specified static color without Solaar or OpenRGB participating. The program must use metadata/probing rather than `/dev/hidraw7`, perform runtime feature discovery, report errors clearly, and exit after the operation.

## Development sequence

The detailed, independently testable work items are:

1. [Exact enumeration](slices/01-exact-enumeration.md)
2. [hidapi access](slices/02-hidapi-access.md)
3. [Harmless HID++ query](slices/03-hidpp-query.md)
4. [Feature discovery](slices/04-feature-discovery.md)
5. [RGB capability query](slices/05-rgb-capabilities.md)
6. [One-zone color change](slices/06-one-zone-color.md)
7. [Complete G733 static color](slices/07-g733-static-color.md)
8. [G502 interface probing](slices/08-g502-interface-probing.md)
9. [G502 static RGB](slices/09-g502-static-rgb.md)
10. [Keyboard interface probing](slices/10-keyboard-interface-probing.md)
11. [Shared abstraction](slices/11-shared-abstraction.md)
12. [Configuration](slices/12-configuration.md)
13. [Startup enumeration](slices/13-startup-enumeration.md)
14. [udev monitoring](slices/14-udev-monitoring.md)
15. [Reconnect/readiness handling](slices/15-reconnect-readiness.md)
16. [Corsair Vengeance DDR5 RAM](slices/16-corsair-ram.md)
17. [Root system service](slices/17-root-system-service.md)
18. [Standalone fan RGB experiment](slices/18-fan-rgb-test.md)
19. [Motherboard/fan RGB in the service](slices/19-motherboard-rgb-service.md)
