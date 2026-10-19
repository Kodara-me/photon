from types import SimpleNamespace
import unittest
from unittest import mock

from photon.monitor import DeviceMonitor, event_identity, target_for_event, run_monitor


class FakeDevice(dict):
    def __init__(self, properties, sys_path="/sys/class/hidraw/hidraw3"):
        super().__init__(properties)
        self.sys_path = sys_path


class DeviceMonitorTests(unittest.TestCase):
    def test_filters_to_supported_logitech_product(self):
        device = FakeDevice({"ID_VENDOR_ID": "046D", "ID_MODEL_ID": "C095"})
        self.assertEqual(target_for_event(device), "g502")
        self.assertEqual(target_for_event(FakeDevice({"ID_VENDOR_ID": "046d", "ID_MODEL_ID": "c547"})), "g502")
        self.assertIsNone(target_for_event(FakeDevice({"ID_VENDOR_ID": "1234", "ID_MODEL_ID": "c095"})))
        self.assertIsNone(target_for_event(FakeDevice({"ID_VENDOR_ID": "046d", "ID_MODEL_ID": "ffff"})))
        self.assertEqual(target_for_event(FakeDevice({"ID_VENDOR_ID": "048D", "ID_MODEL_ID": "5702"})), "motherboard")
        self.assertIsNone(target_for_event(FakeDevice({"ID_VENDOR_ID": "048d", "ID_MODEL_ID": "5711"})))
        self.assertIsNone(target_for_event(FakeDevice({"ID_VENDOR_ID": "1e71", "ID_MODEL_ID": "300e"})))

    def test_identity_prefers_physical_path(self):
        device = FakeDevice({"ID_PATH": "pci-0000:00:14.0-usb-0:8.4:1.2"})
        self.assertEqual(event_identity(device), "pci-0000:00:14.0-usb-0:8.4")

    def test_startup_retries_each_target_independently(self):
        results = {
            "g733": [SimpleNamespace(applied=(), failures=("G733: busy",)), SimpleNamespace(applied=("G733",), failures=())],
            "g502": [SimpleNamespace(applied=("G502",), failures=())],
            "keyboard": [SimpleNamespace(applied=("Keyboard",), failures=())],
            "ram": [SimpleNamespace(applied=("RAM",), failures=())],
            "motherboard": [SimpleNamespace(applied=(), failures=("controller not ready",)),
                            SimpleNamespace(applied=("Motherboard",), failures=())],
        }
        calls = []
        delays = []
        monitor = DeviceMonitor(
            color=(1, 2, 3),
            apply=lambda color, target: calls.append((color, target)) or results[target].pop(0),
            retry_delays=(0.25,),
            sleep=delays.append,
        )
        self.assertTrue(monitor.apply_startup())
        self.assertEqual(
            calls,
            [
                ((1, 2, 3), "g733"),
                ((1, 2, 3), "g733"),
                ((1, 2, 3), "g502"),
                ((1, 2, 3), "keyboard"),
                ((1, 2, 3), "ram"),
                ((1, 2, 3), "motherboard"),
                ((1, 2, 3), "motherboard"),
            ],
        )
        self.assertEqual(delays, [0.25, 0.25])

    def test_late_motherboard_event_retries_then_applies_and_stops(self):
        calls = []
        delays = []
        ready = [False, False, True]
        def apply(color, target):
            calls.append(target)
            return SimpleNamespace(applied=(target,) if ready.pop(0) else (), failures=("not ready",))
        monitor = DeviceMonitor(color=(1, 2, 3), apply=apply, retry_delays=(0.5, 1.0), sleep=delays.append)
        self.assertTrue(monitor.handle_event(FakeDevice({"ID_VENDOR_ID": "048d", "ID_MODEL_ID": "5702"})))
        self.assertEqual(calls, ["motherboard"] * 3)
        self.assertEqual(delays, [0.5, 1.0])

    def test_failed_readiness_has_a_bounded_number_of_attempts(self):
        apply = mock.Mock(return_value=SimpleNamespace(applied=(), failures=("not ready",)))
        delays = []
        monitor = DeviceMonitor(color=(1, 2, 3), apply=apply, sleep=delays.append)
        with self.assertLogs("photon.monitor", level="WARNING"):
            self.assertFalse(monitor.handle_event(FakeDevice({"ID_VENDOR_ID": "048d", "ID_MODEL_ID": "5702"})))
        self.assertEqual(apply.call_count, 4)
        self.assertEqual(delays, [0.5, 1.0, 2.0])

    def test_udev_subscription_starts_before_startup_application(self):
        udev = mock.Mock()
        udev.poll.return_value = None
        def startup():
            udev.start.assert_called_once_with()
        with mock.patch("photon.monitor.pyudev.Context"), \
             mock.patch("photon.monitor.pyudev.Monitor.from_netlink", return_value=udev), \
             mock.patch.object(DeviceMonitor, "apply_startup", side_effect=startup), \
             mock.patch("photon.monitor.ReceiverNotificationManager"), \
             mock.patch("photon.monitor.G733NotificationManager"), \
             mock.patch("tools.photon_enumerate.enumerate_devices", return_value=[]):
            run_monitor()

    def test_duplicate_interfaces_for_one_device_are_debounced(self):
        calls = []
        now = [10.0]
        monitor = DeviceMonitor(
            color=(1, 2, 3),
            apply=lambda color, target: calls.append(target) or SimpleNamespace(applied=(target,), failures=()),
            retry_delays=(),
            debounce_seconds=3.0,
            clock=lambda: now[0],
        )
        device = FakeDevice({"ID_VENDOR_ID": "046d", "ID_MODEL_ID": "c339", "ID_PATH": "keyboard"})
        self.assertTrue(monitor.handle_event(device))
        self.assertFalse(monitor.handle_event(device))
        now[0] = 13.1
        self.assertTrue(monitor.handle_event(device))
        self.assertEqual(calls, ["keyboard", "keyboard"])
