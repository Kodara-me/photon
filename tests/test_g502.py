import json
import unittest
from unittest import mock

from photon.g502_x_plus import G502Probe, claim_rgb_control, prepare_rgb_effects, set_g502_perkey_color
from photon.g733 import G733Capabilities, Zone
from photon.hidpp import DEFAULT_DEVICE_INDEX, FeatureInfo
from tools.photon_g502_probe import g502_probe_candidates, select_unique_rgb_probe


def rgb_probe(path: str, *, status: str = "rgb_capable") -> G502Probe:
    capabilities = G733Capabilities(
        feature=FeatureInfo(0x8070, 4, 0, 3),
        zone_count=1,
        readable=True,
        capabilities=3,
        zones=(Zone(0, 2, 2, (0, 1)),),
    )
    return G502Probe(path, {"hidapi_path": path}, capabilities=capabilities, status=status)


class G502ProbeTests(unittest.TestCase):
    def test_direct_usb_candidates_keep_the_default_device_index(self):
        candidates = g502_probe_candidates([
            {
                "vendor_id": "046d",
                "product_id": "c095",
                "interfaces": [{"hidapi_path": "/dev/hidraw5"}],
            }
        ])
        self.assertEqual(candidates[0].device_index, DEFAULT_DEVICE_INDEX)
        self.assertEqual(candidates[0].transport, "direct")

    def test_receiver_candidates_use_only_a_descriptor_verified_hidpp_interface(self):
        candidates = g502_probe_candidates([
            {
                "vendor_id": "046d",
                "product_id": "c547",
                "interfaces": [
                    {"hidapi_path": "/dev/hidraw2", "report_ids": [1]},
                    {"hidapi_path": "/dev/hidraw5", "report_ids": [0x10, 0x11]},
                ],
            }
        ])
        self.assertEqual([candidate.interface["hidapi_path"] for candidate in candidates], ["/dev/hidraw5"] * 6)
        self.assertEqual([candidate.device_index for candidate in candidates], [1, 2, 3, 4, 5, 6])
        self.assertTrue(all(candidate.transport == "receiver" for candidate in candidates))

    def test_selects_the_only_rgb_capable_interface(self):
        selected = select_unique_rgb_probe([
            rgb_probe("/dev/hidraw2"),
            rgb_probe("/dev/hidraw3", status="no_feature_set"),
        ])
        self.assertEqual(selected.path, "/dev/hidraw2")

    def test_rejects_no_rgb_capable_interfaces(self):
        with self.assertRaisesRegex(RuntimeError, "found 0"):
            select_unique_rgb_probe([rgb_probe("/dev/hidraw2", status="no_rgb_feature")])

    def test_rejects_ambiguous_rgb_capable_interfaces(self):
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            select_unique_rgb_probe([rgb_probe("/dev/hidraw2"), rgb_probe("/dev/hidraw3")])

    def test_probe_result_is_json_ready(self):
        result = G502Probe(
            "/dev/hidraw2", {"hidapi_path": "/dev/hidraw2"}, 3, "receiver", capabilities=rgb_probe("x").capabilities,
            status="rgb_capable",
        ).as_dict()
        decoded = json.loads(json.dumps(result))
        self.assertEqual(decoded["status"], "rgb_capable")
        self.assertEqual(decoded["device_index"], 3)
        self.assertEqual(decoded["transport"], "receiver")
        self.assertEqual(decoded["capabilities"]["zones"][0]["effect_ids"], [0, 1])

    def test_prepare_rgb_effects_uses_g502_effect_count(self):
        class Client:
            def __init__(self):
                self.calls = []

            def feature_request(self, feature_index, function, payload):
                self.calls.append((feature_index, function, payload))

        client = Client()
        probe = rgb_probe("/dev/hidraw5")
        capabilities = G733Capabilities(
            feature=FeatureInfo(0x8071, 9, 0, 2),
            zone_count=1,
            readable=False,
            capabilities=4,
            zones=probe.capabilities.zones,
        )
        prepare_rgb_effects(client, capabilities)
        self.assertEqual(client.calls, [(9, 0x10, bytes.fromhex("ff 01 00 00 00 00 00 00 00 00 00 00 01"))])

    def test_claim_rgb_control_uses_host_mode(self):
        class Client:
            def __init__(self):
                self.calls = []

            def feature_request(self, feature_index, function, payload):
                self.calls.append((feature_index, function, payload))

        client = Client()
        capabilities = G733Capabilities(
            feature=FeatureInfo(0x8071, 9, 0, 2),
            zone_count=1,
            readable=False,
            capabilities=4,
            zones=(Zone(0, 0, 1, (1,)),),
        )
        claim_rgb_control(client, capabilities)
        self.assertEqual(client.calls, [(9, 0x50, bytes.fromhex("01 03 04"))])

    def test_perkey_color_paints_all_g502_led_addresses_and_commits(self):
        class Client:
            def __init__(self):
                self.calls = []

            def feature_request(self, feature_index, function, payload):
                self.calls.append((feature_index, function, payload))

        client = Client()
        features = (FeatureInfo(0x8081, 10, 0, 2),)
        set_g502_perkey_color(client, features, (0xFF, 0, 0))
        self.assertEqual(
            client.calls,
            [
                (10, 0x60, bytes.fromhex("ff 00 00 01 02 03 04 05 06 07 08")),
                (10, 0x70, bytes.fromhex("00 00 00 00 00")),
            ],
        )

    def test_apply_uses_the_selected_receiver_device_index(self):
        from tools import photon_apply

        probe = G502Probe(
            "/dev/hidraw5", {"hidapi_path": "/dev/hidraw5"}, 3, "receiver", capabilities=rgb_probe("x").capabilities,
            status="rgb_capable",
        )
        session = mock.MagicMock()
        session.__enter__.return_value = session
        client = mock.Mock()
        with (
            mock.patch("tools.photon_apply.probe_g502_interfaces", return_value=[probe]),
            mock.patch("tools.photon_apply.HidTransport") as transport,
            mock.patch("tools.photon_apply.HidppClient", return_value=client) as hidpp_client,
            mock.patch("tools.photon_apply.claim_rgb_control"),
            mock.patch("tools.photon_apply.prepare_rgb_effects"),
            mock.patch("tools.photon_apply.set_zone_color"),
            mock.patch("tools.photon_apply.set_g502_perkey_color"),
        ):
            transport.return_value.open_session.return_value = session
            photon_apply._apply_g502((1, 2, 3), False)
        hidpp_client.assert_called_once_with(session, device_index=3, force_long_reports=True, trace=None)


if __name__ == "__main__":
    unittest.main()
