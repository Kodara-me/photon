import unittest
from unittest import mock

from photon.receiver_notifications import (
    ConnectionTransitions,
    RECEIVER_NOTIFICATION_FLAGS,
    RECEIVER_NOTIFICATION_WRITE,
    enable_connection_notifications,
    parse_connection_notification,
    receiver_notification_paths,
)


class ReceiverNotificationTests(unittest.TestCase):
    def test_only_an_offline_to_online_edge_is_admitted(self):
        transitions = ConnectionTransitions()
        online = parse_connection_notification(bytes.fromhex("10 01 41 04 01 34 12"))
        offline = parse_connection_notification(bytes.fromhex("10 01 41 04 41 34 12"))
        self.assertFalse(transitions.became_online(online))
        self.assertFalse(transitions.became_online(online))
        self.assertFalse(transitions.became_online(offline))
        self.assertTrue(transitions.became_online(online))
        self.assertFalse(transitions.became_online(online))

    def test_ignores_non_connection_reports(self):
        self.assertIsNone(parse_connection_notification(bytes.fromhex("11 01 41 04 01 34 12")))

    def test_selects_only_the_receiver_vendor_hidpp_channel(self):
        devices = [{"vendor_id": "046d", "product_id": "c547", "interfaces": [
            {"hidapi_path": "/dev/hidraw5", "report_ids": ()},
            {"hidapi_path": "/dev/hidraw7", "report_ids": (0x10, 0x11)},
        ]}]
        self.assertEqual(receiver_notification_paths(devices), ("/dev/hidraw7",))

    @mock.patch("photon.receiver_notifications.HidppClient")
    def test_enables_receiver_wireless_notifications_once(self, client_type):
        enable_connection_notifications(mock.Mock())
        client_type.return_value.request.assert_called_once_with(
            RECEIVER_NOTIFICATION_WRITE, RECEIVER_NOTIFICATION_FLAGS
        )
