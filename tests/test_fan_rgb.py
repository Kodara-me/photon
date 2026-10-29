import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photon import gigabyte_rgb as fan_rgb
from experiments import fan_rgb as experiment


# Exact 64-byte CC60 response supplied by the user from the host on 2026-10-02.
HOST_REPLY = bytes.fromhex(
    "cc 01 00 07 03 05 05 00 00 00 00 00 49 54 35 37 "
    "30 31 2d 47 49 47 41 42 59 54 45 20 56 33 2e 35 "
    "2e 35 2e 30 00 00 00 00 00 01 02 00 02 00 01 00 "
    "02 00 01 00 00 01 02 00 00 01 01 57 00 00 00 00"
)


class FanRgbTests(unittest.TestCase):
    def test_static_packet_matches_protocol_and_uses_only_selected_bank(self):
        reports = fan_rgb.static_reports(["led-c1"], (0x12, 0x34, 0x56))
        expected_effect = bytes.fromhex(
            "cc 21 02 00 00 00 00 00 00 00 00 01 ff 00 56 34 12 00"
        ) + bytes(46)
        expected_commit = bytes.fromhex("cc 28 02 00 00 00") + bytes(58)
        self.assertEqual(reports, [expected_effect, expected_commit])

    def test_all_external_headers_do_not_touch_accent_banks_or_flash(self):
        reports = fan_rgb.static_reports(list(fan_rgb.HEADERS), (139, 92, 246))
        self.assertEqual([p[1] for p in reports], [0x32, 0x25, 0x26, 0x21, 0x24, 0x28])
        self.assertEqual(struct.unpack_from("<I", reports[-1], 2)[0], 0x72)
        self.assertTrue(all(len(p) == 64 for p in reports))

    def test_unknown_headers_and_duplicate_selection_are_rejected(self):
        for headers in ([], ["fan1"], ["led-c1", "led-c1"]):
            with self.assertRaises(ValueError):
                fan_rgb.static_reports(headers, (1, 2, 3))

    def test_eight_slot_test_stages_every_bank_and_commits_the_complete_mask(self):
        reports = fan_rgb.static_slot_reports(list(range(8)), (0, 255, 0))
        self.assertEqual([p[1] for p in reports], [0x32, *range(0x20, 0x28), 0x28])
        self.assertEqual(reports[-1], bytes.fromhex("cc 28 ff 00 00 00") + bytes(58))
        self.assertEqual([struct.unpack_from("<I", p, 2)[0] for p in reports[1:-1]],
                         [1, 2, 4, 8, 16, 32, 64, 128])

    def test_single_numeric_slot_and_rejected_out_of_range_slot(self):
        reports = fan_rgb.static_slot_reports([7], (0, 255, 0))
        self.assertEqual(reports[0][:18], bytes.fromhex(
            "cc 27 80 00 00 00 00 00 00 00 00 01 ff 00 00 ff 00 00"
        ))
        self.assertEqual(reports[-1][:6], bytes.fromhex("cc 28 80 00 00 00"))
        for slots in ([-1], [8], [7, 7]):
            with self.assertRaises(ValueError):
                fan_rgb.static_slot_reports(slots, (0, 255, 0))

    @unittest.skipIf(fan_rgb.fcntl is None, "hidraw ioctls are Linux-only")
    def test_short_write_is_not_reported_as_success(self):
        with mock.patch.object(fan_rgb.fcntl, "ioctl", return_value=12), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "short feature-report write"):
                fan_rgb.send_feature(9, fan_rgb.cc_report(0x60))

    @unittest.skipIf(fan_rgb.fcntl is None, "hidraw ioctls are Linux-only")
    def test_information_reply_and_open_device_identity(self):
        def ioctl(_fd, command, buffer, _mutate):
            if command == 0x80084803:
                buffer[:] = struct.pack("=IHH", 3, 0x048D, 0x5702)
                return 0
            if command == 0xC0404807:
                buffer[:] = HOST_REPLY
            return 64

        with mock.patch.object(fan_rgb.fcntl, "ioctl", side_effect=ioctl), contextlib.redirect_stdout(io.StringIO()):
            fan_rgb.validate_opened_device(9)
            info = fan_rgb.query_info(9)
        fan_rgb.validate_info(info)
        self.assertEqual(info["firmware"], "3.5.5.0")
        self.assertEqual(info["description"], "IT5701-GIGABYTE V3.5.5.0")
        self.assertEqual(info["chip_id"], "0x57010100")
        self.assertEqual(info["strip_detect"], 7)
        self.assertEqual(info["support_flags"], 0)
        for field, wrong in (
            ("chip_id", "0x00000000"), ("chip_id", "0x0130015f"),
            ("controller_number", 1), ("firmware", "3.5.14.0"),
            ("description", "unknown"), ("product", 0),
        ):
            with self.subTest(field=field, wrong=wrong), self.assertRaisesRegex(RuntimeError, "identity differs"):
                fan_rgb.validate_info({**info, field: wrong})

    def test_changed_descriptor_is_rejected_before_opening_device(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            dmi = root / "dmi"
            dmi.mkdir()
            (dmi / "board_name").write_text(fan_rgb.BOARD_NAME)
            hid_root = root / "hidraw"
            usb = root / "usb-device"
            interface = usb / "interface"
            device = interface / "hid-device"
            device.mkdir(parents=True)
            (usb / "idVendor").write_text("048d")
            (usb / "idProduct").write_text("5702")
            (interface / "bInterfaceNumber").write_text("00")
            (device / "uevent").write_text("HID_ID=0003:0000048D:00005702\n")
            (device / "report_descriptor").write_bytes(fan_rgb.EXPECTED_DESCRIPTOR)
            (hid_root / "hidraw99").mkdir(parents=True)
            (hid_root / "hidraw99/device").symlink_to(device)
            found = fan_rgb.discover_controller(hid_root, root / "dev", dmi)
            self.assertEqual(found.node, root / "dev/hidraw99")
            (device / "report_descriptor").write_bytes(b"different")
            with self.assertRaisesRegex(RuntimeError, "descriptor differs"):
                fan_rgb.discover_controller(hid_root, root / "dev", dmi)

    def test_dry_run_never_opens_controller(self):
        controller = fan_rgb.Controller(Path("/dev/fake"), Path("/sys/fake"), Path("/sys/usb"))
        with mock.patch.object(experiment, "discover_controller", return_value=controller), \
             mock.patch.object(fan_rgb.os, "open") as opener, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(experiment.main(["set", "--all-headers", "--color", "#8B5CF6", "--dry-run"]), 0)
        opener.assert_not_called()

    def test_service_operation_checks_readiness_before_transferring_verified_sequence(self):
        controller = fan_rgb.Controller(Path("/dev/fake"), Path("/sys/fake"), Path("/sys/usb"))
        events = []
        with mock.patch.object(fan_rgb, "discover_controller", return_value=controller), \
             mock.patch.object(fan_rgb, "require_rgb_apps_absent"), \
             mock.patch.object(fan_rgb, "_open_controller", return_value=9), \
             mock.patch.object(fan_rgb, "validate_opened_device", side_effect=lambda fd: events.append("identity")), \
             mock.patch.object(fan_rgb, "query_info", side_effect=lambda fd, **kwargs: events.append("ready") or dict(fan_rgb.VERIFIED_INFO)), \
             mock.patch.object(fan_rgb, "send_feature", side_effect=lambda fd, packet, **kwargs: events.append(packet)), \
             mock.patch.object(fan_rgb.time, "sleep"), \
             mock.patch.object(fan_rgb.os, "close") as close:
            fan_rgb.apply_static_color((0, 255, 0))
        self.assertEqual(events[:2], ["identity", "ready"])
        self.assertEqual(events[2:], fan_rgb.static_slot_reports(list(range(8)), (0, 255, 0)))
        close.assert_called_once_with(9)

    def test_service_operation_closes_unready_or_changed_controller_without_rgb_writes(self):
        for response in (RuntimeError("information not ready"), {**fan_rgb.VERIFIED_INFO, "chip_id": "0x00000000"}):
            with self.subTest(response=response), \
                 mock.patch.object(fan_rgb, "discover_controller"), \
                 mock.patch.object(fan_rgb, "require_rgb_apps_absent"), \
                 mock.patch.object(fan_rgb, "_open_controller", return_value=9), \
                 mock.patch.object(fan_rgb, "validate_opened_device"), \
                 mock.patch.object(fan_rgb, "query_info") as query, \
                 mock.patch.object(fan_rgb, "send_feature") as send, \
                 mock.patch.object(fan_rgb.os, "close") as close:
                if isinstance(response, Exception):
                    query.side_effect = response
                else:
                    query.return_value = response
                with self.assertRaises(RuntimeError):
                    fan_rgb.apply_static_color((0, 255, 0))
                send.assert_not_called()
                close.assert_called_once_with(9)

    def test_service_operation_stops_and_closes_on_a_failed_rgb_transfer(self):
        with mock.patch.object(fan_rgb, "discover_controller"), \
             mock.patch.object(fan_rgb, "require_rgb_apps_absent"), \
             mock.patch.object(fan_rgb, "_open_controller", return_value=9), \
             mock.patch.object(fan_rgb, "validate_opened_device"), \
             mock.patch.object(fan_rgb, "query_info", return_value=dict(fan_rgb.VERIFIED_INFO)), \
             mock.patch.object(fan_rgb, "send_feature", side_effect=RuntimeError("short transfer")) as send, \
             mock.patch.object(fan_rgb.os, "close") as close:
            with self.assertRaisesRegex(RuntimeError, "short transfer"):
                fan_rgb.apply_static_color((0, 255, 0))
        self.assertEqual(send.call_count, 1)
        close.assert_called_once_with(9)
