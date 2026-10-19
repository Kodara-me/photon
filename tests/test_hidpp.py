import unittest
from unittest import mock

from photon.g733 import (
    COLOR_LED_EFFECTS,
    RGB_EFFECTS,
    Zone,
    _discover_color_led_effects,
    static_color_payload,
)
from photon.hidpp import FeatureInfo, HidppClient, HidppError


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.writes = []

    def write_report(self, report):
        self.writes.append(report)
        return len(report)

    def read_report(self, max_length, timeout_ms):
        return self.responses.pop(0) if self.responses else b""


class HidppTests(unittest.TestCase):
    def test_root_feature_lookup_builds_expected_short_report(self):
        session = FakeSession([bytes.fromhex("10 ff 00 0b 05 00 02")])
        client = HidppClient(session, timeout_ms=10)
        feature = client.get_feature_index(0x0001)
        self.assertEqual(feature.index, 5)
        self.assertEqual(feature.flags, 0)
        self.assertEqual(feature.version, 2)
        self.assertEqual(session.writes, [bytes.fromhex("10 ff 00 0b 00 01 00")])

    def test_response_with_unrelated_report_is_ignored(self):
        session = FakeSession([
            bytes.fromhex("10 01 00 0b 09 00 00"),
            bytes.fromhex("10 ff 00 0b 05 00 02"),
        ])
        feature = HidppClient(session, timeout_ms=10).get_feature_index(0x0001)
        self.assertEqual(feature.index, 5)

    def test_feature_error_is_decoded_as_missing_candidate(self):
        session = FakeSession([bytes.fromhex("10 ff 00 0b ff 04 00")])
        self.assertIsNone(HidppClient(session, timeout_ms=10).get_feature_index(0x8070))

    def test_feature_set_enumeration_returns_runtime_feature_ids(self):
        session = FakeSession([
            bytes.fromhex("10 ff 00 0b 05 00 02"),
            bytes.fromhex("10 ff 05 0b 02 00 00"),
            bytes.fromhex("10 ff 05 1b 80 70 00"),
            bytes.fromhex("10 ff 05 1b 1d 4b 40"),
        ])
        features = HidppClient(session, timeout_ms=10).list_features()
        self.assertEqual(features, [
            FeatureInfo(0x8070, 1, 0, 0),
            FeatureInfo(0x1D4B, 2, 0x40, 0),
        ])
        self.assertEqual(session.writes, [
            bytes.fromhex("10 ff 00 0b 00 01 00"),
            bytes.fromhex("10 ff 05 0b 00 00 00"),
            bytes.fromhex("10 ff 05 1b 01 00 00"),
            bytes.fromhex("10 ff 05 1b 02 00 00"),
        ])

    def test_rgb_effects_information_response_starting_with_ff_is_valid(self):
        session = FakeSession([bytes.fromhex("11 ff 09 0b ff 00 01 00 33 00 04 05") + b"\x00" * 8])
        response = HidppClient(session, force_long_reports=True).feature_request(
            9, 0, b"\xff\xff\x00"
        )
        self.assertEqual(response.payload[:7], bytes.fromhex("ff 00 01 00 33 00 04"))

    def test_long_report_is_padded_to_twenty_bytes(self):
        session = FakeSession([bytes.fromhex("11 ff 12 3b") + b"\x00" * 16])
        client = HidppClient(session, timeout_ms=10)
        client.request(0x1234, b"\x01" * 14)
        self.assertEqual(len(session.writes[0]), 20)
        self.assertEqual(session.writes[0][:4], bytes.fromhex("11 ff 12 3b"))

    def test_force_long_reports_uses_long_framing_for_short_payloads(self):
        session = FakeSession([bytes.fromhex("11 ff 00 0b") + b"\x00" * 16])
        HidppClient(session, force_long_reports=True).request(0x0000, b"\x80\x70")
        self.assertEqual(len(session.writes[0]), 20)
        self.assertEqual(session.writes[0][:6], bytes.fromhex("11 ff 00 0b 80 70"))

    def test_timeout_is_bounded_and_reported(self):
        session = FakeSession([])
        with self.assertRaises(HidppError) as context:
            HidppClient(session, timeout_ms=1).request(0x0000)
        self.assertIn("timeout", str(context.exception))

    def test_static_color_payload_for_8070(self):
        zone = Zone(index=2, location=5, effect_count=2, effect_ids=(1, 2))
        function, payload = static_color_payload(zone, (0x8B, 0x5C, 0xF6), COLOR_LED_EFFECTS)
        self.assertEqual(function, 0x30)
        self.assertEqual(payload, bytes.fromhex("02 01 8b 5c f6 03 00 00 00 00 00 00"))

    def test_static_color_payload_for_8071_omits_repeated_effect_id(self):
        zone = Zone(index=0, location=0, effect_count=1, effect_ids=(1,))
        function, payload = static_color_payload(zone, (0xFF, 0x00, 0x00), RGB_EFFECTS)
        self.assertEqual(function, 0x10)
        self.assertEqual(payload, bytes.fromhex("00 00 ff 00 00 02 00 00 00 00 00 00 01"))

    def test_hidpp_error_report_matches_original_request(self):
        session = FakeSession([bytes.fromhex("11 ff ff 09 1b 05") + b"\x00" * 14])
        with self.assertRaisesRegex(HidppError, "feature error 0x05"):
            HidppClient(session, force_long_reports=True).request(0x091b)

    def test_color_led_effect_ids_are_two_byte_fields(self):
        class CapabilityClient:
            def __init__(self):
                self.responses = [
                    bytes.fromhex("02 00 01 00 03"),
                    bytes.fromhex("00 00 02 04"),
                    bytes.fromhex("00 00 00 00"),
                    bytes.fromhex("00 01 00 01"),
                    bytes.fromhex("00 02 00 0a c1 15 00 04"),
                    bytes.fromhex("00 03 00 03 c0 05 00 06"),
                    bytes.fromhex("01 00 02 04"),
                    bytes.fromhex("01 00 00 00"),
                    bytes.fromhex("01 01 00 01"),
                    bytes.fromhex("01 02 00 0a c1 15 00 04"),
                    bytes.fromhex("01 03 00 03 c0 05 00 06"),
                ]

            def feature_request(self, feature_index, function, params=b""):
                return type("Response", (), {"payload": self.responses.pop(0)})()

        capabilities = _discover_color_led_effects(
            CapabilityClient(), FeatureInfo(COLOR_LED_EFFECTS, 4, 0, 3)
        )
        self.assertEqual(capabilities.zones[0].effect_ids, (0, 1, 10, 3))
        self.assertIn(1, capabilities.zones[0].effect_ids)


if __name__ == "__main__":
    unittest.main()
