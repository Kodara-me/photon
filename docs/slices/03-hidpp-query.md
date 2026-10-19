# Slice 3 — send one harmless HID++ query

## Objective

Confirm HID++ transport and report framing on the G733 without changing state.

## Scope

Use the G733 candidate selected by metadata/probing. Send one root-level harmless query and capture transmitted and received bytes, report IDs, lengths, device index, timeout, and response matching behavior.

## Non-goals

Do not send feature writes, LED commands, firmware commands, or repeated polling.

## Verification

Run with Solaar and OpenRGB not participating. Repeat once to confirm deterministic framing.

## Done when

A valid HID++ response is received and the transport behavior is recorded rather than assumed.

## Implementation status

Implemented by [`photon/hidpp.py`](../../photon/hidpp.py) and [`tools/photon_hidpp_query.py`](../../tools/photon_hidpp_query.py). The command performs one runtime-selected G733 `Root.GetFeature(Feature Set)` query, supports `--trace`, and exits after closing the session.

The live response gate is still pending because this execution environment does not expose the enumerated `/dev/hidraw7` node.
