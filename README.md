# Photon

Linux RGB controller for this project's Logitech devices, Corsair DDR5 RAM, and
the verified Gigabyte motherboard/fan RGB controller.

## Install the standalone bundle

Keep `dist/photon` anywhere, including your home directory. It includes Python,
hidapi and pyudev; the target does not need Python or pip installed.

```sh
chmod +x ~/photon
~/photon service check
sudo ~/photon service install
```

Installation copies the executable to `/usr/local/lib/photon/photon`,
creates `/usr/local/bin/photon`, writes `/etc/systemd/system/photon.service`,
and enables and starts the service at boot. The service runs as root because RAM
control requires SMBus access. Repeating installation updates and restarts it.
Existing `/etc/photon/config.toml` is preserved. Once installed, the original
downloaded file can be moved or removed.

Photon was formerly named KiraLights. Installing over a `kira-lights` installation
stops and removes `kira-lights.service`, its executable and its command link, and
copies `/etc/kira-lights/config.toml` to `/etc/photon/config.toml` when no Photon
configuration exists yet. The old configuration file is left in place; remove
`/etc/kira-lights` once Photon runs as expected.

The host needs Linux with systemd running and libudev available (`libudev1` on
Debian/Ubuntu or `systemd-libs` on Fedora). `service check` reports missing runtime
dependencies without changing anything. Install missing host packages using your
distribution's package manager. The installer does not install packages or load
kernel modules automatically.

USB control needs kernel hidraw support. RAM control additionally needs `i2c-dev`,
the SMBus adapter driver, and kernel-bound `spd5118` DDR5 hubs. A missing `/dev/i2c-*`
warning means RAM access needs host setup; it does not block USB service installation.
No udev permission rules are installed. Stop Solaar and OpenRGB before starting RGB
control. This app supports the specific hardware in `docs/PLAN.md`.

```sh
photon service status
sudo photon service restart
journalctl -u photon.service -b
sudo photon service uninstall
```

Uninstall retains the color configuration. Edit `/etc/photon/config.toml`
(for example, `color = "#8B5CF6"`) and restart to apply a new default color.

The same configured color is applied to all eight motherboard lighting slots,
including the Corsair fans confirmed in the hardware test. This backend is limited
to the verified Z790 AORUS ELITE AX / ITE IT5701 controller and firmware 3.5.5.0.
It changes lighting only; fan and pump speeds are controlled by their existing tools.

The service checks controller identity and waits for a valid information reply before
RGB writes. It retries startup failures up to four times with short delays, then waits
for udev device-arrival events. It applies once and closes the device after success.
Boot-time physical behavior still needs verification after installation.

```sh
sudo photon motherboard --color '#8B5CF6'
sudo photon probe motherboard --json
```

## Build

```sh
python3 tools/build_bundle.py
```

The build installs pinned dependencies from `requirements-build.txt` into
`build/venv` and produces `dist/photon`. Build on the intended Linux architecture
with a glibc version no newer than your deployment host. This is a Linux binary,
not a cross-platform installer. Building does not install or start the service.
