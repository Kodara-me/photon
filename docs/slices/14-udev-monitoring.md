# Slice 14 — add event-driven udev monitoring

## Objective

Handle later device availability without rapid polling.

## Scope

Use pyudev to monitor relevant `hidraw` add events. Filter by supported VID/PID and metadata, debounce duplicate interfaces, wait for the node to be usable, apply configuration once, and remain idle.

## Non-goals

Do not add a GUI, IPC API, web service, or generalized event bus.

## Verification

Test add events, duplicate interface events, a device already present at startup, and unrelated hidraw activity.

## Done when

The resident process consumes practically no CPU while idle and applies colors only in response to startup or relevant udev events.

