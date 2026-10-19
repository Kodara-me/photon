# Slice 8 — probe G502 X PLUS interfaces

## Objective

Identify which of `046d:c095`'s multiple hidraw interfaces supports the required HID++ protocol.

## Scope

Repeat the harmless query and feature-discovery process against every metadata-derived G502 interface. Record report framing, device index, feature presence, and firmware behavior.

## Non-goals

Do not assume older G502 packet formats or change RGB before the protocol path is confirmed.

## Verification

Test wired operation and document whether the device exposes RGB over this connection.

## Done when

One interface is selected by successful protocol probing, or the limitation is clearly documented.

## Implementation status

Implemented by [`tools/photon_g502_probe.py`](../../tools/photon_g502_probe.py). The probe enumerates every metadata-derived `046d:c095` interface, performs root and RGB feature discovery without RGB writes, reports per-interface JSON and optional packet traces, and selects a path only when exactly one interface is RGB-capable.

The live probe captured from the target machine found `/dev/hidraw5` to be the protocol-capable interface. `/dev/hidraw2` and `/dev/hidraw3` sent the Feature Set query but did not answer. On `/dev/hidraw5`, the root feature set was index `0x01`, `RGB_EFFECTS (0x8071)` resolved to index `0x09`, version `2`, and `PER_KEY_LIGHTING_V2 (0x8081)` resolved to index `0x0a`, version `2`. The `RGB_EFFECTS` information response reported one zone and capability word `0x0004`; this feature is write-capable even though its live-readable bit is clear.

On 2026-08-07, with the G502 paired through its Lightspeed receiver, direct USB product `046d:c095` disappeared and the host exposed a `046d:c547` receiver at USB path `1-8.4`. Its only vendor HID++ channel was `/dev/hidraw5`, verified from its report descriptor (`0x10` and `0x11`); the receiver's two input interfaces were excluded. Receiver support probes candidate paired-device indexes `1` through `6` with harmless feature discovery and accepts a target only after observing both the G502's previously captured `RGB_EFFECTS (0x8071)` and `PER_KEY_LIGHTING_V2 (0x8081)` features. The current execution environment still lacks the corresponding `/dev/hidraw*` nodes, so physical receiver-slot discovery and the RGB write remain to be verified on the target machine.
