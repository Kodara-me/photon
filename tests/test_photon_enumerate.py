import json
import errno
import unittest
from unittest import mock

from photon.hid_transport import HidTransport
from tools.photon_enumerate import _merge_hidapi_entries, _udev_properties, format_text


class EnumerationTests(unittest.TestCase):
    def test_hidapi_collection_records_are_merged_by_path(self):
        entries = [
            {
                "path": b"/dev/hidraw7",
                "vendor_id": 0x046D,
                "product_id": 0x0AFE,
                "product_string": "G733",
                "usage_page": 12,
                "usage": 1,
            },
            {
                "path": b"/dev/hidraw7",
                "vendor_id": 0x046D,
                "product_id": 0x0AFE,
                "product_string": "G733",
                "usage_page": 0xFF13,
                "usage": 1,
            },
        ]
        merged = _merge_hidapi_entries(entries)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["path"], "/dev/hidraw7")
        self.assertEqual(len(merged[0]["collections"]), 2)

    def test_duplicate_collection_is_not_repeated(self):
        entry = {
            "path": "/dev/hidraw0",
            "vendor_id": 0x046D,
            "product_id": 0xC339,
            "usage_page": 1,
            "usage": 6,
        }
        merged = _merge_hidapi_entries([entry, entry])
        self.assertEqual(merged[0]["collections"], [{"usage_page": 1, "usage": 6}])

    def test_text_output_groups_interfaces(self):
        devices = [
            {
                "product": "G502 X PLUS",
                "vendor_id": "046d",
                "product_id": "c095",
                "serial": "0123ABCD",
                "usb_path": "1-8.4",
                "usb_sysfs_path": "/sys/devices/1-8.4",
                "interfaces": [
                    {"hidraw": "/dev/hidraw2", "interface_number": "00"},
                    {"hidraw": "/dev/hidraw3", "interface_number": "01"},
                ],
            }
        ]
        output = format_text(devices)
        self.assertIn("G502 X PLUS (046d:c095)", output)
        self.assertIn("/dev/hidraw2", output)
        self.assertIn("/dev/hidraw3", output)

    def test_json_is_serializable(self):
        payload = [{"product": "G733", "interfaces": []}]
        encoded = json.dumps(payload, sort_keys=True)
        self.assertEqual(json.loads(encoded), payload)

    def test_transport_opens_and_closes_without_reading(self):
        device = mock.Mock()
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "opened")
        device.open_path.assert_called_once_with(b"/dev/hidraw7")
        device.close.assert_called_once_with()
        device.read.assert_not_called()
        device.write.assert_not_called()

    def test_transport_accepts_native_byte_path(self):
        device = mock.Mock()
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close(b"/dev/hidraw7")
        self.assertEqual(result.status, "opened")
        device.open_path.assert_called_once_with(b"/dev/hidraw7")

    def test_transport_classifies_missing_node(self):
        device_factory = mock.Mock()
        transport = HidTransport(device_factory=device_factory)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=False):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "missing_node")
        device_factory.assert_not_called()

    def test_transport_classifies_permission_error(self):
        device = mock.Mock()
        device.open_path.side_effect = PermissionError(errno.EACCES, "permission denied")
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "permission_denied")
        device.close.assert_not_called()

    def test_transport_classifies_busy_error(self):
        device = mock.Mock()
        device.open_path.side_effect = OSError(errno.EBUSY, "busy")
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "busy")

    def test_transport_preserves_generic_hidapi_error(self):
        device = mock.Mock()
        device.open_path.side_effect = OSError("open failed")
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "transport_error")
        self.assertEqual(result.exception_type, "OSError")
        self.assertEqual(result.error, "open failed")

    def test_transport_reports_close_error(self):
        device = mock.Mock()
        device.close.side_effect = OSError("close failed")
        transport = HidTransport(device_factory=lambda: device)
        with mock.patch("photon.hid_transport.os.path.exists", return_value=True):
            result = transport.probe_open_close("/dev/hidraw7")
        self.assertEqual(result.status, "close_error")
        self.assertEqual(result.error, "close failed")

    @mock.patch("tools.photon_enumerate.pyudev.Devices.from_device_file")
    @mock.patch("tools.photon_enumerate.pyudev.Devices.from_sys_path")
    @mock.patch("tools.photon_enumerate._sysfs_for_hidraw", return_value=None)
    def test_missing_device_node_does_not_abort_udev_lookup(self, _sysfs, from_sys_path, from_file):
        from_file.side_effect = __import__("pyudev").DeviceNotFoundByFileError("missing")
        self.assertEqual(_udev_properties("/dev/hidraw7"), {})
        from_sys_path.assert_not_called()


if __name__ == "__main__":
    unittest.main()
