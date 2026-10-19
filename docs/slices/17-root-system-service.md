# Slice 17 — root system service

## Objective

Run Photon at boot and reapply configured RGB after supported USB devices reconnect.

## Behavior

- `photon monitor` applies each configured target at startup, with bounded readiness retries, then waits on `hidraw` add events.
- It filters Logitech G733 (`046d:0afe`), G502 X PLUS (`046d:c095` or its `046d:c547` Lightspeed receiver), and PRO Gaming Keyboard (`046d:c339`) events, debounces physical multi-interface arrivals, re-enumerates through the existing targeted operation, and closes all handles after use.
- RAM is only applied during startup because its SMBus controller has no matching hidraw event.
- `sudo dist/photon service install` copies the bundle into the machine installation, creates `/usr/local/bin/photon` as a global command, and starts the root systemd unit through that command. `uninstall` removes the unit, executable, and managed command link but retains `/etc/photon/config.toml`.

## Non-goals

Do not install udev permission rules or invoke a new root process from udev. The resident root service already has the access it needs.

## Verification

Test startup application, supported/unsupported event filtering, duplicate interface event debouncing, bounded failure retries, generated unit contents, root requirement, installation flow, and configuration preservation on uninstall.

## Installer bundle (2026-10-02)

The bundle build now installs pinned hidapi and pyudev into its local build environment,
so it does not depend on those Python modules being installed system-wide.
`service check` reports runtime requirements without opening devices or changing system
configuration. Installation checks those requirements before copying files. RAM device
nodes are reported separately because their absence does not prevent USB operation.
See the repository README for installation, upgrade and removal commands.

No new hardware or protocol assumptions are introduced by packaging. Kernel-bound
SPD hubs and controller signatures still require the existing targeted hardware checks.

Verification: the Linux x86-64 one-file bundle built successfully; 18 service and CLI
tests passed. The bundled `service check` loaded hidapi and libudev successfully and
reported absent `/dev/i2c-*` nodes in the build environment. No device commands,
system service installation, system package installation or configuration changes
were performed. Actual installation and RGB behavior remain untested in this session.
