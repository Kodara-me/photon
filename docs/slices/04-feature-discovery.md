# Slice 4 — discover RGB feature indexes

## Objective

Resolve actual feature indexes on the G733 at runtime.

## Scope

Implement only the root/feature discovery needed to search for `0x8070`, `0x8071`, and `0x8081`. Record feature presence, index, version where available, and HID++ errors.

## Non-goals

Do not implement a complete HID++ library or write RGB state.

## Verification

Run against the current G733 firmware and show that feature indexes are obtained from the device rather than constants.

## Done when

The program can reliably say which candidate RGB feature exists and where it is indexed.

## Implementation status

Implemented in [`photon/hidpp.py`](../../photon/hidpp.py) and [`photon/g733.py`](../../photon/g733.py). Candidate feature indexes are resolved at runtime through Root.GetFeature; no feature indexes are hard-coded.

The live G733 feature response is still pending hardware access.
