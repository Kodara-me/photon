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

## Uninstallation

```sh
sudo photon service uninstall
```

This removes the service, the executable and the command link, and keeps
`/etc/photon/config.toml`.

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
