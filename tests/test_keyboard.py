import json
import unittest

from photon.g733 import COLOR_LED_EFFECTS, RGB_EFFECTS
from photon.hidpp import FeatureInfo
from photon.pro_keyboard import KeyboardProbe, claim_led_control, discover_capabilities, information_request


class KeyboardProbeTests(unittest.TestCase):
    def test_information_requests_use_only_known_rgb_contracts(self):
        self.assertEqual(information_request(FeatureInfo(COLOR_LED_EFFECTS, 4, 0, 3)), (0, b""))
        self.assertEqual(information_request(FeatureInfo(RGB_EFFECTS, 9, 0, 2)), (0, b"\xff\xff\x00"))
        self.assertIsNone(information_request(FeatureInfo(0x8081, 10, 0, 2)))

    def test_probe_result_is_json_serializable(self):
        result = KeyboardProbe(
            "/dev/hidraw0",
            {"hidapi_path": "/dev/hidraw0"},
            root=FeatureInfo(0x0001, 1, 0, 2),
            features=(FeatureInfo(RGB_EFFECTS, 9, 0, 2),),
            information={"0x8071": "ff 00 01"},
            status="rgb_feature_found",
        ).as_dict()
        decoded = json.loads(json.dumps(result))
        self.assertEqual(decoded["status"], "rgb_feature_found")
        self.assertEqual(decoded["features"][0]["index"], 9)

    def test_capability_discovery_is_skipped_without_color_led_feature(self):
        class Client:
            pass

        self.assertIsNone(discover_capabilities(Client(), (FeatureInfo(0x8081, 10, 0, 2),)))

    def test_claim_led_control_enables_host_mode(self):
        class Client:
            def __init__(self):
                self.calls = []

            def feature_request(self, feature_index, function, payload):
                self.calls.append((feature_index, function, payload))

        class Capabilities:
            feature = FeatureInfo(0x8070, 13, 0, 5)

        client = Client()
        claim_led_control(client, Capabilities())
        self.assertEqual(client.calls, [(13, 0x80, b"\x01")])


if __name__ == "__main__":
    unittest.main()
