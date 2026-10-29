# Slice 20 - Windows service and reconnect monitoring

## Behavior

`photon service install | uninstall | status | restart | check` manage a Windows service
named `Photon` (`photon/windows_service.py`). It runs `photon.exe monitor --config
%ProgramData%\Photon\config.toml` as LocalSystem, with automatic start (delayed start off),
`PlugPlay` as its only dependency and a restart on failure. `install` copies the executable
to `%ProgramFiles%\Photon\photon.exe`, creates `%ProgramData%\Photon` writable by
Administrators and SYSTEM only, writes the default configuration when absent, and starts the
service; a second `install` stops, updates and restarts it. `uninstall` removes the service
and the executable and keeps the configuration. `check` reports the prerequisites, PawnIO
included, and changes nothing.

`photon/windows_monitor.py` subscribes to HID interface arrivals with
`CM_Register_Notification` before the startup apply, maps an arrival to a target by the VID:PID
of its interface path, and debounces by the USB device instance without its `&MI_xx` suffix.
The service accepts power events and, on `PBT_APMRESUMEAUTOMATIC` (resume from sleep or
hibernation, a Fast Startup power-on included), applies to every device as at startup.

PawnIO can load after the service started and raises no device event: when the startup or
resume apply missed the RAM, `DeviceMonitor` makes single later attempts after 5, 10, 20, 30,
60, 60 and 60 seconds (about four minutes), then gives up with a warning.

## Verified by tests (fakes only)

Arrival mapping, debouncing, retries, the subscription order, resume handling, the service
configuration passed to a fake `win32service`, install, upgrade, uninstall, status, restart,
the elevation refusal, `check`, and the late RAM retries. No test opens a device, PawnIO, the
real Service Control Manager or the registry.

## Not yet verified on hardware

- The sign-in screen after Restart, after Shut down with Fast Startup and after resume from
  sleep or hibernation (manual checks in the README, "Checking the service by hand").
- That Windows delivers `PBT_APMRESUMEAUTOMATIC` to the service through `SvcOtherEx`.
- The USB device instance walk (`CM_Get_Parent`) on the owner's devices; when it fails the
  arrival is debounced by VID:PID.
- The G502 receiver link notifications on Windows, read from the short-report (`0x10`)
  collection of the receiver.
