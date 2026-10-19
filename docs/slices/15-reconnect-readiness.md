# Slice 15 — handle reconnects and readiness failures

## Objective

Make event-driven application reliable across wake, reconnect, suspend, and device disappearance.

## Scope

Add bounded, event-triggered retries for initialization delays, transient busy errors, device disappearance, and receiver/device readiness. Re-enumerate after reconnect rather than reusing stale paths.

## Non-goals

Do not introduce one-second forever polling or retain open device handles unnecessarily.

## Verification

Test powered-off-at-login then enabled later, mouse wake, receiver reconnect, suspend/resume, removal during a request, permission failure, and unsupported firmware/protocol responses.

## Done when

The user service applies once after relevant availability transitions, recovers from transient hardware state, remains silent on success, and reports actionable failures.

