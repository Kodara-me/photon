# Photon

[![CI](https://github.com/jstmichel/photon/actions/workflows/ci.yml/badge.svg)](https://github.com/jstmichel/photon/actions/workflows/ci.yml)

*[Version française](README.fr.md)*

Photon is a small Linux service that sets one RGB color on a Logitech headset, mouse and
keyboard, Corsair DDR5 RAM and a Gigabyte motherboard with its fans. It applies the color at
boot and again whenever a device reconnects, then leaves the devices alone. No vendor
software, no GUI, no polling.

## Supported hardware

Photon drives only hardware whose protocol was verified on a real device. Anything else is
refused rather than guessed.

| Device | Identifier | Link |
|---|---|---|
| Logitech G733 Gaming Headset | `046d:0afe` | HID++ over USB |
| Logitech G502 X Plus | `046d:c095`, or its Lightspeed receiver `046d:c547` | HID++ |
| Logitech PRO Gaming Keyboard | `046d:c339` | HID++ over USB |
| Corsair Vengeance RGB DDR5 | `CMH64GX5M2B5600C40` | SMBus (`i2c-dev`) |
| Gigabyte Z790 AORUS ELITE AX, ITE IT5701 controller, firmware 3.5.5.0 | `048d:5702` | HID over USB |

The motherboard backend sets all eight lighting slots, which includes fans wired to its RGB
headers. It changes lighting only; fan and pump speeds stay with their own tools.

## Requirements

- Linux with systemd running, kernel `hidraw` support and libudev (`systemd-libs` on Arch
  and Fedora, `libudev1` on Debian and Ubuntu).
- For the RAM: `i2c-dev`, the SMBus adapter driver and kernel-bound `spd5118` DDR5 hubs. A
  missing `/dev/i2c-*` only disables the RAM; the rest still works.
- Solaar and OpenRGB stopped: they compete for the same devices.

The bundle carries its own Python, hidapi and pyudev; the host needs neither Python nor pip.

## Installation

### One command

```sh
curl -fsSL https://github.com/jstmichel/photon/releases/latest/download/get-photon.sh | sh
```

The script downloads the latest bundle, checks it against the release's `SHA256SUMS`, runs
`photon service check`, asks before installing, then runs `sudo photon service install`. It
stops early when that version is already installed. Options: `--version v0.1.0`, `--yes`,
`--dry-run` (pass them with `| sh -s -- --dry-run`). Read it first if you like:
[scripts/get-photon.sh](scripts/get-photon.sh).

### By hand

Download the bundle of the latest release, check it, and install the service:

```sh
curl -LO https://github.com/jstmichel/photon/releases/latest/download/photon
curl -LO https://github.com/jstmichel/photon/releases/latest/download/SHA256SUMS
sha256sum --check --ignore-missing SHA256SUMS
chmod +x photon
./photon service check
sudo ./photon service install
```

`service check` reports missing runtime dependencies without changing anything; the
installer neither installs packages nor loads kernel modules.

`service install` copies the bundle to `/usr/local/lib/photon/photon`, links
`/usr/local/bin/photon` to it, writes `/etc/systemd/system/photon.service`, then enables and
starts the service. The service runs as root because RAM control needs SMBus access, and it
already holds the `hidraw` nodes, so no udev rules are installed. Running the install again
upgrades and restarts it. The downloaded file can be removed afterwards.

### Coming from KiraLights

Photon was formerly named KiraLights. Installing over a `kira-lights` installation stops and
removes `kira-lights.service`, its executable and its command link, and copies
`/etc/kira-lights/config.toml` to `/etc/photon/config.toml` when no Photon configuration
exists yet. The old configuration file is left in place: remove `/etc/kira-lights` once
Photon runs as expected.

## Configuration

`/etc/photon/config.toml` holds the color, created on first install:

```toml
color = "#8B5CF6"
```

After editing it, apply it with `sudo photon service restart`. The file is kept across
upgrades and uninstallation.

## Usage

```sh
photon service status
sudo photon service restart
journalctl -u photon.service -b
```

The service waits for each controller to answer before writing, retries startup failures up
to four times, then waits for udev device-arrival events. It applies once and closes each
device.

The same commands work by hand, for one device or all of them:

```sh
sudo photon apply --color '#8B5CF6'
sudo photon apply --only ram --color '#FF0000'
sudo photon g733 --color '#00FF00' --zone 0
sudo photon motherboard --color '#8B5CF6'
```

Read-only probes report what Photon sees without writing any color:

```sh
sudo photon probe g502 --json
sudo photon probe ram --json
sudo photon probe motherboard --json
```

`photon --help` and `photon <command> --help` list every option; `--trace` shows the
protocol traffic.

## Windows

On Windows, Photon sets the color on the Logitech G733, G502 X Plus (wired or through its
receiver), PRO keyboard and Gigabyte Z790 AORUS ELITE AX motherboard, and on the Corsair
Vengeance RGB DDR5 RAM, from the command line or as a background service that applies the
color at boot, on resume and on every device reconnect. `photon apply` reports every device
it could not reach, with the reason, and applies the others.

Requirements: Windows 10 or 11 and `photon.exe` (built with `python tools\build_bundle.py`,
which produces `dist\photon.exe`). The Logitech devices and the motherboard need no driver.

The RAM needs [PawnIO](https://pawnio.eu), a signed driver that you install yourself from
its official installer; Photon never installs, updates or removes a driver. `photon.exe`
carries PawnIO's signed i801 SMBus module and uses `PawnIOLib.dll` from
`%ProgramFiles%\PawnIO`. The RAM is also reached only from an **elevated prompt** (Run as
administrator). Without PawnIO, without elevation, or while another program holds the
Windows SMBus mutex, the RAM is reported unavailable with the reason and the other devices
are still applied. Close hardware monitors that read the SMBus if the mutex stays busy.

Disable the vendor lighting first. Photon does not stop, reconfigure or detect other
software, and a device that another program holds is reported as unavailable:

1. In Logitech G HUB, open each device, go to its lighting settings and turn the lighting
   off (or quit G HUB).
2. In Windows Settings, open Personalization, Dynamic Lighting and turn off "Use Dynamic
   Lighting on my devices" (or turn it off for the devices Photon manages).

Then run it from a prompt:

```bat
photon.exe apply --color "#8B5CF6"
photon.exe g733 --color "#00FF00" --zone 0
photon.exe probe g502 --json
```

The options and the output are the same as on Linux. Without `--color`, the color comes from
`%ProgramData%\Photon\config.toml`, in the same format as on Linux; a missing file means
the default color.

### Windows service

Download `photon.exe` and `SHA256SUMS` from the latest release and check the file:

```bat
certutil -hashfile photon.exe SHA256
```

The hash must match the `photon.exe` line of `SHA256SUMS`. Then, from an **elevated prompt**
(Run as administrator):

```bat
photon.exe service check
photon.exe service install
```

`service check` reports the missing prerequisites without changing anything; a missing
PawnIO disables the RAM only. `service install`:

- copies the executable to `%ProgramFiles%\Photon\photon.exe`;
- creates `%ProgramData%\Photon\config.toml` with the default color when it is absent, in a
  folder that only Administrators and SYSTEM can write to;
- creates the `Photon` service, running as LocalSystem, with automatic start (not delayed),
  `PlugPlay` as its only dependency, and a restart on failure, then starts it.

Running the install again upgrades the executable and restarts the service. The service
starts during boot, before anybody signs in, and applies the configured color to every
available device, so the sign-in screen already shows it. It applies again when the machine
resumes from sleep or hibernation, which includes the power-on after a Shut down with Fast
Startup, and whenever a supported device is plugged in or reconnects. If PawnIO's driver
loads after the service started, the RAM is retried for a few minutes. Its log is
`%ProgramData%\Photon\photon.log`.

```bat
photon.exe service status
photon.exe service restart
```

`restart`, `install` and `uninstall` need an elevated prompt and change nothing without one.
After editing `%ProgramData%\Photon\config.toml`, apply it with `photon.exe service restart`.

#### Checking the service by hand

The sign-in screen cannot be checked by a test. After installing, with the service running,
first set every device to another color so the check shows a change:
`photon.exe apply --color "#FF0000"`.

1. **Restart.** From the Start menu, choose Restart. At the sign-in screen, without signing
   in, every connected supported device shows the configured color.
2. **Shut down with Fast Startup.** Set another color as above, choose Shut down (Fast
   Startup on, the default), then power the machine on. At the sign-in screen every
   connected supported device shows the configured color.
3. **Resume from sleep.** Set another color as above, choose Sleep from the Start menu, wait
   for the machine to be asleep, then wake it with the keyboard or the power button. On the
   lock screen, without signing in, every connected supported device shows the configured
   color. Repeat with Hibernate (`shutdown /h`) if you like. `%ProgramData%\Photon\photon.log`
   then has a line `resumed from sleep or hibernation`.
4. **Reconnect.** Unplug a supported device (or switch the G733 off and on), and plug it back:
   it shows the configured color again.

## Uninstallation

```sh
sudo photon service uninstall
```

This removes the service, the executable and the command link, and keeps
`/etc/photon/config.toml`.

On Windows, from an elevated prompt:

```bat
photon.exe service uninstall
```

This stops and removes the service and `%ProgramFiles%\Photon\photon.exe`, and keeps
`%ProgramData%\Photon\config.toml`.

## Building from source

```sh
python3 tools/build_bundle.py
build/venv/bin/python -m unittest discover -s tests -p 'test_*.py'
sudo dist/photon service install
```

The build installs the pinned `requirements-build.txt` into `build/venv` and produces
`dist/photon`, a Linux binary for the build machine's architecture. Build on a system whose
glibc is no newer than the target's. Building does not install or start anything.

The design is in [docs/PLAN.md](docs/PLAN.md), and each verified step, with its hardware
observations, is in [docs/slices/](docs/slices/).

## Contributing

Ideas, bug reports and new hardware are welcome: see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
