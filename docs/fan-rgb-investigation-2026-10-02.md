# Fan RGB investigation — 2026-10-02

Read-only sysfs USB/HID and DMI inspection found:

- Motherboard: Gigabyte Z790 AORUS ELITE AX.
- ITE motherboard controller: `048d:5702`, USB physical path `1-13`, HID interface 0.
- NZXT Kraken Base: `1e71:300e`, USB physical path `1-12.1`.
- No Corsair USB device (`1b1c`) was present in the observed enumeration.

The current ITE hidraw node is ephemeral and must not be used as a persistent identifier.
No HID reports were sent, no devices were opened, and no fan speed, lighting, service,
udev or external application configuration was changed.

OpenRGB's detector explicitly recognizes `048d:5702` as Gigabyte RGB Fusion 2 USB,
using HID usage page `0xff89` and usage `0xcc`. These selectors still require local
descriptor verification before implementing control:

https://raw.githubusercontent.com/CalcProgrammer1/OpenRGB/master/Controllers/GigabyteRGBFusion2USBController/GigabyteRGBFusion2USBControllerDetect.cpp

Corsair Lighting Node and Commander controller protocols have upstream references:

https://github.com/liquidctl/liquidctl/blob/main/liquidctl/driver/commander_pro.py

Feasibility: motherboard RGB control is a plausible route if the fans' lighting wires
connect to its RGB/ARGB headers. A Corsair USB-controller backend cannot be selected
from the currently observed hardware. Fan model, actual lighting wiring, controller
presence/power, LED count, and physical channel mapping remain unknown. USB metadata
cannot identify passive fans attached to an RGB header.

Next step: confirm the fan model and whether its lighting wires terminate at a
Corsair USB hub or a motherboard RGB/ARGB header. Then inspect the exact controller
protocol and descriptors before a separately authorized, targeted static-color test.

The user subsequently authorized a standalone lighting experiment. See
[Slice 18](slices/18-fan-rgb-test.md) for the test command, verified descriptor,
candidate headers, protocol details and current verification limits.
