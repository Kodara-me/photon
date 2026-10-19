# Slice 11 — extract the small shared abstraction

## Objective

Remove accidental duplication only after the three devices work independently.

## Scope

Extract transport, HID++ request/response, feature lookup, error types, static-color intent, and common device metadata. Keep device modules responsible for quirks and payload generation.

## Non-goals

Do not create a generic HID++ or RGB plugin framework.

## Verification

Run each device-specific command and ensure packet output is unchanged from the proven implementations.

## Implementation status — 2026-08-07

Completed after independent live verification of the G733, G502 X PLUS, and PRO Gaming Keyboard.

- `photon/rgb.py` contains the shared RGB feature candidates, zone/capability model,
  0x8070/0x8071 discovery, color parsing, and static-color request construction.
- `photon/probe.py` contains the common probe-result serialization used by the G502 and
  keyboard probes.
- `photon/hid_transport.py` and `photon/hidpp.py` remain the shared transport and
  HID++ request/response layers.
- Device modules retain only device identity, probe policy, and hardware-specific control
  sequences. In particular, the G502 claim/prepare/per-key commit sequence and keyboard host
  control claim were not generalized.
- `photon/g733.py` remains a compatibility facade for the established G733 imports.

Verification: `python3 -m unittest discover -s tests -q` passes all 34 tests. Existing packet
payload regression tests continue to assert the proven 0x8070 and 0x8071 byte sequences; no live
RGB command was issued during this refactor.

## Done when

Shared code is smaller than the duplicated code and each device remains independently understandable.
