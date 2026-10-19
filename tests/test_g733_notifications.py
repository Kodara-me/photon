import unittest

from photon.g733_notifications import (
    G733LivenessTransitions,
    adc_measurement_is_online,
    g733_notification_paths,
)


class G733NotificationTests(unittest.TestCase):
    def test_only_an_offline_to_online_edge_is_admitted(self):
        transitions = G733LivenessTransitions()
        self.assertFalse(transitions.became_online(True))
        self.assertFalse(transitions.became_online(True))
        self.assertFalse(transitions.became_online(False))
        self.assertTrue(transitions.became_online(True))
        self.assertFalse(transitions.became_online(True))

    def test_selects_only_a_long_report_g733_channel(self):
        devices = [{"vendor_id": "046d", "product_id": "0afe", "interfaces": [
            {"hidapi_path": "/dev/hidraw0", "report_ids": (0x11,)},
            {"hidapi_path": "/dev/hidraw4", "report_ids": (0x02, 0x06)},
        ]}]
        self.assertEqual(g733_notification_paths(devices), ("/dev/hidraw0",))

    def test_adc_measurement_requires_a_nonzero_voltage(self):
        self.assertFalse(adc_measurement_is_online(b""))
        self.assertFalse(adc_measurement_is_online(bytes.fromhex("00 00 00")))
        self.assertTrue(adc_measurement_is_online(bytes.fromhex("0e f1 01")))
