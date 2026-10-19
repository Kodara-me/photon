"""Small HID++ 2.0 subset used by the Photon G733 proof of concept."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from .hid_transport import HidSession

SHORT_REPORT_ID = 0x10
LONG_REPORT_ID = 0x11
SHORT_REPORT_LENGTH = 7
LONG_REPORT_LENGTH = 20
MAX_READ_LENGTH = 64
DEFAULT_DEVICE_INDEX = 0xFF
DEFAULT_SOFTWARE_ID = 0x0B
FEATURE_SET = 0x0001


class HidppError(RuntimeError):
    def __init__(self, message: str, *, code: int | None = None, request_id: int | None = None):
        super().__init__(message)
        self.code = code
        self.request_id = request_id


@dataclass(frozen=True)
class HidppResponse:
    report_id: int
    device_index: int
    request_id: int
    payload: bytes
    raw: bytes


@dataclass(frozen=True)
class FeatureInfo:
    feature_id: int
    index: int
    flags: int
    version: int


class HidppClient:
    def __init__(
        self,
        session: HidSession,
        *,
        device_index: int = DEFAULT_DEVICE_INDEX,
        software_id: int = DEFAULT_SOFTWARE_ID,
        timeout_ms: int = 1000,
        force_long_reports: bool = False,
        trace: Callable[[str, bytes], None] | None = None,
    ):
        self.session = session
        self.device_index = device_index
        self.software_id = software_id & 0x0F
        self.timeout_ms = timeout_ms
        self.force_long_reports = force_long_reports
        self.trace = trace

    def _request_id(self, request_id: int) -> int:
        if request_id < 0x8000:
            return (request_id & 0xFFF0) | self.software_id
        return request_id

    def _build_report(self, request_id: int, params: bytes) -> bytes:
        body = request_id.to_bytes(2, "big") + params
        if not self.force_long_reports and len(body) <= SHORT_REPORT_LENGTH - 2:
            report_id, length = SHORT_REPORT_ID, SHORT_REPORT_LENGTH
        elif len(body) <= LONG_REPORT_LENGTH - 2:
            report_id, length = LONG_REPORT_ID, LONG_REPORT_LENGTH
        else:
            raise HidppError("HID++ request payload is too large", request_id=request_id)
        report = bytes([report_id, self.device_index]) + body
        return report.ljust(length, b"\x00")

    def request(self, request_id: int, params: bytes = b"") -> HidppResponse:
        wire_request_id = self._request_id(request_id)
        report = self._build_report(wire_request_id, bytes(params))
        if self.trace:
            self.trace("tx", report)
        self.session.write_report(report)

        deadline = time.monotonic() + self.timeout_ms / 1000
        while time.monotonic() < deadline:
            remaining = max(1, int((deadline - time.monotonic()) * 1000))
            raw = self.session.read_report(MAX_READ_LENGTH, remaining)
            if not raw:
                continue
            if self.trace:
                self.trace("rx", raw)
            response = self._parse_response(raw, wire_request_id)
            if response is None:
                continue
            return response
        raise HidppError(f"timeout waiting for HID++ response to 0x{wire_request_id:04x}", request_id=wire_request_id)

    def _parse_response(self, raw: bytes, request_id: int) -> HidppResponse | None:
        if len(raw) < 4 or raw[0] not in (SHORT_REPORT_ID, LONG_REPORT_ID):
            return None
        report_id, device_index = raw[0], raw[1]
        if device_index not in (self.device_index, self.device_index ^ 0xFF):
            return None
        response_id = int.from_bytes(raw[2:4], "big")

        # HID++ error reports encode the failed request as 0xff, feature
        # index, function, error code. They do not echo the normal request
        # ID in bytes 2..3, so recognize them before ordinary matching.
        if (
            raw[2] == 0xFF
            and len(raw) >= 6
            and raw[3] == (request_id >> 8) & 0xFF
            and raw[4] == request_id & 0xFF
        ):
            code = raw[5]
            raise HidppError(
                f"HID++ feature error 0x{code:02x}",
                code=code,
                request_id=request_id,
            )
        if response_id != request_id:
            return None
        payload = raw[4:]
        # 0xff is normally the HID++ error marker, but RGB_EFFECTS
        # information responses legitimately begin with ``ff 00``. A real
        # feature error carries a nonzero error code in the following byte.
        if payload[:1] == b"\xff" and len(payload) > 1 and payload[1] != 0:
            code = payload[1] if len(payload) > 1 else None
            raise HidppError(
                f"HID++ feature error 0x{code:02x}" if code is not None else "HID++ feature error",
                code=code,
                request_id=request_id,
            )
        if payload[:1] == b"\x8f":
            code = payload[3] if len(payload) > 3 else None
            raise HidppError("HID++ legacy error", code=code, request_id=request_id)
        return HidppResponse(report_id, device_index, response_id, payload, raw)

    def feature_request(self, feature_index: int, function: int = 0, params: bytes = b"") -> HidppResponse:
        return self.request((feature_index << 8) | (function & 0xFF), params)

    def get_feature_index(self, feature_id: int) -> FeatureInfo | None:
        try:
            response = self.feature_request(0, 0, feature_id.to_bytes(2, "big"))
        except HidppError as exc:
            if exc.code in (0x04, 0x05, 0x06, 0x07):
                return None
            raise
        if len(response.payload) < 3:
            raise HidppError("short Root.GetFeature response", request_id=response.request_id)
        index, flags, version = response.payload[:3]
        return FeatureInfo(feature_id, index, flags, version) if index else None

    def get_feature_set_index(self) -> FeatureInfo | None:
        return self.get_feature_index(FEATURE_SET)

    def list_features(self) -> list[FeatureInfo]:
        """Return the device's advertised HID++ feature table.

        The feature-set calls are read-only.  They are useful when a device
        emits a notification for a runtime feature which is not part of the
        standard feature catalogue we otherwise query directly.
        """
        feature_set = self.get_feature_set_index()
        if feature_set is None:
            return []
        count_payload = self.feature_request(feature_set.index, 0).payload
        if not count_payload:
            raise HidppError("short FeatureSet.GetCount response")
        features: list[FeatureInfo] = []
        for index in range(1, count_payload[0] + 1):
            # HID++ reserves the low nibble for the software ID, therefore
            # protocol function 1 is encoded as 0x10 on the wire.
            response = self.feature_request(feature_set.index, 0x10, bytes([index]))
            if len(response.payload) < 3:
                raise HidppError("short FeatureSet.GetFeatureID response")
            feature_id = int.from_bytes(response.payload[:2], "big")
            flags = response.payload[2]
            features.append(FeatureInfo(feature_id, index, flags, 0))
        return features

    def discover_features(self, feature_ids: tuple[int, ...]) -> list[FeatureInfo]:
        found: list[FeatureInfo] = []
        for feature_id in feature_ids:
            info = self.get_feature_index(feature_id)
            if info is not None:
                found.append(info)
        return found
