# Slice 18 — standalone fan RGB experiment

## Objective

Identify which Gigabyte motherboard lighting header drives the user's three Corsair
fans and apply a static color once. The user authorized this experiment on 2026-10-02.

## Scope and stopping point

Add a standalone Python test under `experiments/`, outside the bundled application.
Discover the exact `048d:5702` controller from sysfs, verify its board and HID descriptor,
query controller information, and expose the four reference RGB headers plus the
eight documented effect banks for the expanded mapping test.
Log each feature report and result, then close. Stop after one color application
and obtain the user's physical observation before integration.

Do not change fan speeds, NZXT pump control, system services, udev, CoolerControl or
other applications. Do not reset the controller, change calibration or LED counts,
write flash, or continuously stream packets. Require Solaar/OpenRGB to be absent.

## Verified metadata and remaining assumptions

The board identifies as Z790 AORUS ELITE AX. Its `048d:5702` HID interface 0 advertises
usage page `0xff89`, usage `0xcc`, report ID `0xcc`, with 63 data bytes (64 including ID).
The exact two-collection descriptor was read from sysfs. The device node currently
requires root. The host information probe is recorded below; physical lighting-header
mapping and RGB command support still require testing.

Protocol reference, not an implementation dependency:

- [Feature report and static-effect packet structures](https://raw.githubusercontent.com/CalcProgrammer1/OpenRGB/master/Controllers/GigabyteRGBFusion2USBController/GigabyteRGBFusion2USBController.h)
- [Information query, hardware-effect selection, static color and commit](https://raw.githubusercontent.com/CalcProgrammer1/OpenRGB/master/Controllers/GigabyteRGBFusion2USBController/GigabyteRGBFusion2USBController.cpp)
- [Board signature and header layout](https://raw.githubusercontent.com/CalcProgrammer1/OpenRGB/master/Controllers/GigabyteRGBFusion2USBController/GigabyteFusion2USB_Devices.cpp)
- [Header protocol indexes](https://raw.githubusercontent.com/CalcProgrammer1/OpenRGB/master/Controllers/GigabyteRGBFusion2USBController/GigabyteFusion2USB_Devices.h)

The newer reference table associates identifier `0x0130015f`, controller number 0
with this board. This machine's older firmware instead returns chip ID `0x57010100`;
the board-table identifier must not be used as its measured chip ID. Candidate external
header indexes are D_LED1=5, D_LED2=6, LED_C1=1, LED_C2=4. Those names are
protocol-reference mappings until physically verified.

## Run from the repository in a normal host terminal

Only the Python standard library is required. Close Solaar/OpenRGB before RGB writes.

```sh
sudo python3 experiments/fan_rgb.py probe
sudo python3 experiments/fan_rgb.py set --all-headers --color '#8B5CF6'
```

`probe` sends `CC 60` then reads the 64-byte information report; it changes no color.
`set` repeats the query, checks the measured controller identity, sends `CC 32 00` to
enable built-in effects on both ARGB headers, stages static BGR colors in the four
external header banks, and commits only those banks with `CC 28 72`. All reports
are 64 bytes including the report ID and are printed in full along with ioctl results.
USB acceptance does not prove a physical color change.

To identify the fan connection after the broad header test, change one header at a
time to a distinct color and observe the fans:

```sh
sudo python3 experiments/fan_rgb.py set --header d-led1 --color '#00FF00'
sudo python3 experiments/fan_rgb.py set --header d-led2 --color '#00FF00'
sudo python3 experiments/fan_rgb.py set --header led-c1 --color '#00FF00'
sudo python3 experiments/fan_rgb.py set --header led-c2 --color '#00FF00'
```

Stop as soon as the fan header is identified. ARGB hardware-effect enable is shared
by both D_LED headers; even a single D_LED test can change the other header's mode.
RGB headers may drive other attached lighting. The experiment does not save to flash,
but restoring an earlier effect requires the previous controller settings, which
cannot be recovered from the information report.

`set ... --dry-run` verifies sysfs metadata and prints planned packets without
opening the device. Board, USB interface, descriptor, opened VID/PID and information
identity mismatches stop RGB writes; short transfers stop the sequence immediately.

## Verification — 2026-10-02

Seven focused tests passed, covering known packet bytes/BGR order, external bank mask,
identity/signature checks, unexpected descriptors, short transfers and dry-run behavior.
Live dry-run discovery matched this board's ITE controller and feature-report descriptor.
The root probe attempt was blocked by the execution environment's `no new privileges`
restriction before the Python command ran. No controller queries or RGB writes were
sent in this session. Actual firmware/signature, USB acceptance and physical fan colors
remain unverified. No packages, services, system settings or external applications were
changed. The installed and built bundles were not rebuilt or modified.

## Host probe supplied by the user — 2026-10-02

The user ran `sudo python3 experiments/fan_rgb.py probe` in the host terminal.
`CC 60` write and the corresponding feature read each returned 64 bytes. Response:

```text
cc 01 00 07 03 05 05 00 00 00 00 00 49 54 35 37
30 31 2d 47 49 47 41 42 59 54 45 20 56 33 2e 35
2e 35 2e 30 00 00 00 00 00 01 02 00 02 00 01 00
02 00 01 00 00 01 02 00 00 01 01 57 00 00 00 00
```

Decoded: product byte 1, controller number 0, strip-detect byte 7, firmware 3.5.5.0,
description `IT5701-GIGABYTE V3.5.5.0`, chip ID `0x57010100`, three ARGB count-code
bytes zero, support flags zero. A zero count code is an enum, not proof of zero LEDs.
Do not infer the fans' LED count or wiring from these fields.

The initial `board_signature` output label and reference-value guard were too strict
for this measured firmware. They have been replaced with `chip_id` and checks against
the actual product/controller/firmware/description/chip ID, while retaining DMI board,
USB and descriptor checks. The exact response is now a regression fixture.
The subsequent host color result is recorded below. Static color and header mapping
remain experimental.

## First color test and expanded slot test — 2026-10-02

The user supplied the output of `set --all-headers --color '#8B5CF6'` and reported
that the fans did not change. The information reply matched the earlier probe.
Every feature write returned 64 bytes: information selector `CC60`, mode enable
`CC3200`, purple static effect banks `CC25/20`, `CC26/40`, `CC21/02`, `CC24/10`,
and commit `CC28/72` (notation is command followed by zone mask, in hexadecimal).
The color bytes at offsets 14..17 were `f6 5c 8b 00`. USB transport success does
not establish that firmware applied a command. No physical fan mapping is established.

The user reports approximately eight entries in CoolerControl and one controls fan
RGB. The exact device and entry names have not yet been supplied. The reference
effect-packet encoder supports eight banks `0x20..0x27`, selected by bits 0..7.
Their match to CoolerControl's entries is a hypothesis, not verified hardware mapping.
Added `--slot 0..7` and `--all-slots` for a bounded experiment on those banks.

```sh
sudo python3 experiments/fan_rgb.py set --all-slots --color '#00FF00'
```

This stages green in all eight banks, including onboard lighting, and sends the
full `CC28/FF` commit. It uses the same verified controller identity and framing
checks. It does not reset the controller, save flash, change LED counts/calibration,
or add unrelated commands. Both D_LED hardware-effect modes are enabled as in the
initial test. Individual slots can subsequently be tested with `--slot N`.

Nine focused tests passed after this extension. Live dry-run verified the eight
planned effect banks and full commit mask; no new hardware commands were run by
the assistant. The first physical failure is preserved here rather than treated
as evidence that RGB writes work. Fan speed, services and existing bundles remain
outside this experiment.

## Physical success — 2026-10-02

After running `set --all-slots --color '#00FF00'`, the user confirmed the fan lighting
turned green. This establishes that the eight-bank static-effect experiment can
control the physical fan RGB on the measured IT5701 controller. It does not identify
which bank drives the fans or establish whether a partial commit works on this firmware.
The full write trace for the successful run has not been supplied.

Next observable step: apply a contrasting color to one slot at a time with `--slot N`
and identify the controlling index from the user's observation. Start with slot 0;
slots 2, 3 and 7 were also absent from the initial four-header test. Do not infer a
mapping from that earlier failure alone because the commit mask also changed between
experiments. Keep this outside the bundle/service until a targeted change is verified.

The user subsequently chose uniform color across all eight slots and explicitly
requested service integration. See [Slice 19](19-motherboard-rgb-service.md); the
single-slot identification step is no longer required for the requested behavior.
The intervening slot-0 purple test left the fans green according to the user. That
does not identify a different slot or prove partial commit support.
