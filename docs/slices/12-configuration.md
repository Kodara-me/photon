# Slice 12 — add minimal configuration

## Objective

Load one configured static color and apply it to every supported device that is present.

## Scope

Use a small TOML configuration file. This slice deliberately has one global color rather than
per-device values, so a single setting can control the G733, G502 X PLUS, and PRO Gaming Keyboard
together. Validate the hex color and reject unknown keys. Keep the default path explicit.

The default service path is `/etc/photon/config.toml`. This location is readable by a root
service before a graphical/user session starts. If the file is absent, Photon defaults to
the default color, `#8B5CF6`; an existing but invalid file remains an error. Development tools may pass
an alternate path; this slice does not create the system directory or change permissions.

Example:

```toml
color = "#8B5CF6"
```

The device color commands also accept no `--color` argument; they resolve the configured color,
falling back to `#8B5CF6` when the file is absent. Likewise, omitting both `--zone` and `--all`
selects all discovered zones. `--zone N` remains available for targeted verification.

## Non-goals

No database, GUI, dynamic reload, profiles, or configuration migration system.

## Verification

Test valid configuration, missing configuration, malformed colors, unknown keys, and an omitted
color.

## Done when

A configuration object can provide one validated color to a later one-shot/startup apply command,
which will apply it to all currently available supported devices.

## Implementation status — 2026-08-07

Implemented in `photon/config.py` with `PhotonConfig`, `load_config()`, and clear
`ConfigError` messages. Missing configuration uses `#8B5CF6`. The configuration parser uses
Python's standard-library `tomllib`; no package installation is required. The one-shot application
and startup enumeration are covered by Slices 13–15.
