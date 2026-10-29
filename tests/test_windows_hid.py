"""The HID command line on Windows, against a fake hidapi backend (R1, R2, R13, R14, R16, R17).

Nothing here opens a real device: a fake ``hid`` module answers a small HID++ subset.
``sys.platform`` is patched to ``win32`` so the same tests run on Linux and on Windows.
"""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photon import __main__ as cli
from photon import config, host
from photon.hid_transport import HidTransport, HidTransportError
from tools import photon_apply, photon_enumerate

GUID = b"{4d1e55b2-f16f-11cf-88cb-001111000030}"


def hid_path(instance: bytes) -> bytes:
    return b"\\\\?\\HID#" + instance + b"#" + GUID


G733_PATH = hid_path(b"VID_046D&PID_0AFE&MI_03&Col02#8&10f1421&0&0001")
G733_OTHER = hid_path(b"VID_046D&PID_0AFE&MI_03&Col03#8&10f1421&0&0002")
G733_CONSUMER = hid_path(b"VID_046D&PID_0AFE&MI_03&Col01#8&10f1421&0&0000")
KEYBOARD_LONG = hid_path(b"VID_046D&PID_C339&MI_01&Col03#8&c9cc6cf&0&0002")
KEYBOARD_OTHER = hid_path(b"VID_046D&PID_C339&MI_01&Col04#8&c9cc6cf&0&0003")
KEYBOARD_TYPING = hid_path(b"VID_046D&PID_C339&MI_00#8&30740491&0&0000") + b"\\KBD"
RECEIVER_SHORT = hid_path(b"VID_046D&PID_C547&MI_02&Col01#8&34f46378&0&0000")
RECEIVER_LONG = hid_path(b"VID_046D&PID_C547&MI_02&Col02#8&34f46378&0&0001")
G502_WIRED = hid_path(b"VID_046D&PID_C095&MI_02&Col02#8&1a2b3c4d&0&0001")

COLOR_LED_EFFECTS = 0x8070
RGB_EFFECTS = 0x8071
PER_KEY_LIGHTING_V2 = 0x8081
RED = (0xFF, 0x00, 0x00)


class Endpoint:
    """One HID path of the fake bus and the HID++ device behind it."""

    def __init__(self, path, vendor_id, product_id, product, usage_page, usage, interface_number, *,
                 features=None, answering=(0xFF,), zones=1, open_error=None, write_error=None):
        self.entry = {
            "path": path, "vendor_id": vendor_id, "product_id": product_id, "serial_number": "",
            "release_number": 0x100, "product_string": product, "usage_page": usage_page,
            "usage": usage, "interface_number": interface_number, "bus_type": 1,
        }
        self.path = path
        self.features = {0x0001: 1, **(features or {})}
        self.answering = set(answering)
        self.zones = zones
        self.open_error = open_error
        self.write_error = write_error
        self.writes: list[tuple[int, int, bytes]] = []
        self.opened = 0


class FakeHidBackend:
    """Stands in for the ``hid`` module of hidapi."""

    def __init__(self, *endpoints):
        self.endpoints = {endpoint.path: endpoint for endpoint in endpoints}

    def enumerate(self, vendor_id=0, product_id=0):
        return [dict(endpoint.entry) for endpoint in self.endpoints.values()]

    def device(self):
        return FakeDevice(self)

    def writes(self, feature_id):
        return [
            write for endpoint in self.endpoints.values() for write in endpoint.writes if write[0] == feature_id
        ]


class FakeDevice:
    def __init__(self, backend):
        self._backend = backend
        self._endpoint = None
        self._replies = []

    def open_path(self, path):
        endpoint = self._backend.endpoints[path]
        if endpoint.open_error is not None:
            raise endpoint.open_error
        endpoint.opened += 1
        self._endpoint = endpoint

    def close(self):
        self._endpoint = None

    def write(self, report):
        endpoint = self._endpoint
        if endpoint.write_error is not None:
            raise endpoint.write_error
        report = bytes(report)
        self._replies.append(self._answer(endpoint, report))
        return len(report)

    def read(self, length, timeout_ms=0):
        return list(self._replies.pop(0)) if self._replies else []

    @staticmethod
    def _answer(endpoint, request):
        device_index = request[1]
        if device_index not in endpoint.answering:
            # HID++ 2.0 error 0x04 (no such feature): what an empty receiver slot answers.
            return (bytes([0x11, device_index, 0xFF]) + request[2:4] + b"\x04").ljust(20, b"\x00")
        feature_index, function, params = request[2], request[3] & 0xF0, request[4:]
        by_index = {index: feature_id for feature_id, index in endpoint.features.items()}
        feature_id = 0 if feature_index == 0 else by_index.get(feature_index)
        payload = b""
        if feature_id == 0:
            index = endpoint.features.get(int.from_bytes(params[:2], "big"), 0)
            payload = bytes([index, 0, 0])
        elif feature_id == 0x0001:
            payload = bytes([len(endpoint.features)])
        elif feature_id == COLOR_LED_EFFECTS:
            if function == 0x00:
                payload = bytes([endpoint.zones, 0, 0, 0, 1])
            elif function == 0x10:
                payload = bytes([params[0], 0, params[0] + 1, 1])
            elif function == 0x20:
                payload = bytes([params[0], params[1], 0, 1])
        elif feature_id == RGB_EFFECTS and function == 0x00:
            payload = bytes([0, 0, endpoint.zones, 0, 0, 0, 1])
        if feature_id and function >= 0x10:
            endpoint.writes.append((feature_id, function, bytes(params)))
        return (bytes([0x11, device_index]) + request[2:4] + payload).ljust(20, b"\x00")


def lighting_features(*feature_ids):
    return {feature_id: 5 + position for position, feature_id in enumerate(feature_ids)}


def g733(**kwargs):
    return Endpoint(G733_PATH, 0x046D, 0x0AFE, "G733 Gaming Headset", 0xFF43, 0x0202, 3,
                    features=lighting_features(COLOR_LED_EFFECTS), zones=2, **kwargs)


def keyboard(**kwargs):
    return Endpoint(KEYBOARD_LONG, 0x046D, 0xC339, "PRO Gaming Keyboard", 0xFF43, 0x0602, 1,
                    features=lighting_features(COLOR_LED_EFFECTS), zones=3, **kwargs)


def g502_wired(**kwargs):
    return Endpoint(G502_WIRED, 0x046D, 0xC095, "G502 X PLUS", 0xFF00, 2, 2,
                    features=lighting_features(RGB_EFFECTS, PER_KEY_LIGHTING_V2), zones=1, **kwargs)


def g502_receiver(**kwargs):
    return Endpoint(RECEIVER_LONG, 0x046D, 0xC547, "USB Receiver", 0xFF00, 2, 2,
                    features=lighting_features(RGB_EFFECTS, PER_KEY_LIGHTING_V2), zones=1, answering=(1,), **kwargs)


def noise():
    """Collections that are not HID++ channels and must never be opened."""
    return [
        Endpoint(G733_CONSUMER, 0x046D, 0x0AFE, "G733 Gaming Headset", 0x0C, 1, 3),
        Endpoint(G733_OTHER, 0x046D, 0x0AFE, "G733 Gaming Headset", 0xFF13, 1, 3),
        Endpoint(KEYBOARD_TYPING, 0x046D, 0xC339, "PRO Gaming Keyboard", 0x01, 6, 0),
        Endpoint(RECEIVER_SHORT, 0x046D, 0xC547, "USB Receiver", 0xFF00, 1, 2),
    ]


@contextlib.contextmanager
def windows(backend):
    """Run as Windows, with the fake hidapi backend behind enumeration and transport."""
    with mock.patch.object(sys, "platform", "win32"), \
            mock.patch.object(photon_enumerate, "hid", backend), \
            mock.patch("photon.hid_transport.hid", backend):
        yield


def run(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


class WindowsApplyTests(unittest.TestCase):
    def test_apply_sets_the_g733_g502_and_keyboard_and_reports_each(self):  # R1
        backend = FakeHidBackend(g733(), keyboard(), g502_wired(), *noise())
        with windows(backend):
            result = photon_apply.apply_available(RED)
        self.assertEqual(
            result.applied,
            ("G733 (2 zone(s))", "G502 X PLUS (1 zone(s) + LEDs)", "PRO Gaming Keyboard (3 zone(s))"),
        )
        self.assertEqual(
            [failure.split(":")[0] for failure in result.failures], ["Corsair RAM", "Gigabyte motherboard RGB"]
        )
        for endpoint in noise():
            self.assertEqual(backend.endpoints[endpoint.path].opened, 0)

    def test_apply_writes_the_color_to_every_zone(self):  # R1
        backend = FakeHidBackend(g733(), keyboard())
        with windows(backend):
            photon_apply.apply_available(RED, only="g733")
            photon_apply.apply_available(RED, only="keyboard")
        zone_writes = [write for write in backend.writes(COLOR_LED_EFFECTS) if write[1] == 0x30]
        self.assertEqual(len(zone_writes), 2 + 3)
        for _, _, params in zone_writes:
            self.assertEqual(params[1:5], bytes([0x01, 0xFF, 0x00, 0x00]))

    def test_apply_reaches_the_g502_through_its_receiver(self):  # R1
        backend = FakeHidBackend(g733(), keyboard(), g502_receiver(), *noise())
        with windows(backend):
            result = photon_apply.apply_available(RED)
        self.assertEqual(len(result.applied), 3)
        self.assertIn("G502 X PLUS (1 zone(s) + LEDs)", result.applied)
        self.assertEqual(backend.writes(PER_KEY_LIGHTING_V2)[0][2][:3], bytes(RED))
        self.assertEqual(backend.endpoints[RECEIVER_SHORT].opened, 0)

    def test_a_busy_device_is_unavailable_while_the_others_are_applied(self):  # R1, R14
        backend = FakeHidBackend(g733(open_error=OSError("open failed")), keyboard(), g502_wired())
        with windows(backend):
            result = photon_apply.apply_available(RED)
        self.assertEqual(result.applied, ("G502 X PLUS (1 zone(s) + LEDs)", "PRO Gaming Keyboard (3 zone(s))"))
        g733_failure = next(item for item in result.failures if item.startswith("G733"))
        self.assertIn("open failed", g733_failure)

    def test_an_unreachable_device_is_unavailable_while_the_others_are_applied(self):  # R1, R14
        backend = FakeHidBackend(g733(), keyboard())
        with windows(backend):
            result = photon_apply.apply_available(RED)
        self.assertEqual(result.applied, ("G733 (2 zone(s))", "PRO Gaming Keyboard (3 zone(s))"))
        self.assertTrue(any(item.startswith("G502 X PLUS:") for item in result.failures))

    def test_a_busy_receiver_leaves_the_other_devices_applied(self):  # R1, R14
        backend = FakeHidBackend(g733(), keyboard(), g502_receiver(open_error=OSError("open failed")))
        with windows(backend):
            result = photon_apply.apply_available(RED)
        self.assertEqual(result.applied, ("G733 (2 zone(s))", "PRO Gaming Keyboard (3 zone(s))"))
        self.assertTrue(any(item.startswith("G502 X PLUS:") for item in result.failures))

    def test_only_the_collection_that_answers_is_used_when_two_are_candidates(self):  # R1
        silent = Endpoint(KEYBOARD_OTHER, 0x046D, 0xC339, "PRO Gaming Keyboard", 0xFF43, 0x0604, 1,
                          write_error=OSError("write failed"))
        backend = FakeHidBackend(keyboard(), silent)
        with windows(backend):
            result = photon_apply.apply_available(RED, only="keyboard")
        self.assertEqual(result.applied, ("PRO Gaming Keyboard (3 zone(s))",))

    def test_ram_and_motherboard_are_reported_unavailable_not_attempted(self):  # R1
        with windows(FakeHidBackend(g733())):
            result = photon_apply.apply_available(RED, only="ram")
        self.assertEqual(result.applied, ())
        self.assertEqual(result.failures, ("Corsair RAM: not supported on Windows yet",))


class WindowsCommandLineTests(unittest.TestCase):
    def test_apply_prints_the_linux_summary_and_unavailable_lines(self):  # R2
        backend = FakeHidBackend(g733(), keyboard(), g502_wired())
        with windows(backend):
            code, out, err = run(["apply", "--color", "#ff0000"])
        self.assertEqual(code, 0)
        self.assertEqual(out, "applied #FF0000 to 3 device target(s)\n")
        self.assertIn("unavailable: Corsair RAM: ", err)

    def test_apply_exits_nonzero_when_nothing_was_applied(self):  # R2
        with windows(FakeHidBackend()):
            code, out, _ = run(["apply", "--color", "#ff0000"])
        self.assertEqual(code, 1)
        self.assertEqual(out, "applied #FF0000 to 0 device target(s)\n")

    def test_device_commands_print_the_linux_output(self):  # R2
        backend = FakeHidBackend(g733(), keyboard(), g502_wired())
        with windows(backend):
            self.assertEqual(run(["g733", "--color", "#ff0000"])[1], "applied #FF0000 to 2 G733 zone(s)\n")
            self.assertEqual(run(["keyboard", "--color", "#ff0000", "--zone", "1"])[1],
                             "applied #FF0000 to 1 keyboard zone(s)\n")
            self.assertEqual(run(["g502", "--color", "#00ff00", "--all"])[1], "applied #00FF00 to 1 G502 zone(s)\n")

    def test_apply_only_and_trace_are_accepted(self):  # R2
        with windows(FakeHidBackend(g733())):
            code, _, err = run(["apply", "--only", "g733", "--color", "#0000ff", "--trace"])
        self.assertEqual(code, 0)
        self.assertIn("tx: 11 ff", err)

    def test_probes_print_the_linux_json_shape(self):  # R2
        backend = FakeHidBackend(g502_receiver(), g733(), *noise())
        with windows(backend):
            code, out, _ = run(["probe", "g502", "--json"])
            self.assertEqual(code, 0)
            probe = json.loads(out)
            statuses = [item["status"] for item in probe["interfaces"]]
            self.assertEqual(statuses.count("rgb_capable"), 1)
            self.assertEqual({item["transport"] for item in probe["interfaces"]}, {"receiver"})
            code, out, _ = run(["probe", "g733", "--json"])
            self.assertEqual(code, 0)
            self.assertEqual(set(json.loads(out)), {"known_features", "advertised_features"})

    def test_every_command_parses_the_same_options_on_both_platforms(self):  # R2
        lines = [
            ["apply", "--color", "#ff0000", "--only", "g733", "--trace", "--config", "c.toml"],
            ["g733", "--zone", "1", "--trace"], ["g502", "--all"], ["keyboard", "--color", "#fff000"],
            ["ram", "--config", "c.toml"], ["motherboard", "--trace"], ["monitor", "--config", "c.toml"],
            ["service", "check"], ["probe", "ram", "--json"], ["probe", "g502", "--json", "--trace"],
            ["probe", "g733-events", "--seconds", "2"], ["probe", "g733", "--json"],
            ["probe", "motherboard", "--json", "--trace"],
        ]
        for argv in lines:
            with mock.patch.object(sys, "platform", "linux"):
                linux = vars(cli.build_parser().parse_args(argv))
            with mock.patch.object(sys, "platform", "win32"):
                other = vars(cli.build_parser().parse_args(argv))
            self.assertEqual(linux, other, argv)


class WindowsEnumerationTests(unittest.TestCase):
    def test_enumeration_groups_vendor_collections_without_linux_fields(self):  # R2, R16
        backend = FakeHidBackend(g733(), keyboard(), g502_receiver(), *noise())
        with windows(backend):
            devices = photon_enumerate.enumerate_devices()
        self.assertEqual([(d["vendor_id"], d["product_id"]) for d in devices],
                         [("046d", "0afe"), ("046d", "c339"), ("046d", "c547")])
        headset = devices[0]
        self.assertEqual(
            sorted(i["hidapi_path"] for i in headset["interfaces"]),
            sorted([G733_PATH.decode(), G733_OTHER.decode()]),
        )
        main = next(i for i in headset["interfaces"] if i["hidapi_path"] == G733_PATH.decode())
        self.assertEqual(main["report_ids"], (0x11,))
        self.assertEqual(main["interface_number"], "03")
        for interface in headset["interfaces"]:
            self.assertNotIn("hidraw", interface)
            self.assertNotIn("sysfs_path", interface)
        self.assertIsNone(headset["usb_path"])
        receiver = devices[2]
        self.assertEqual([i["hidapi_path"] for i in receiver["interfaces"]].count(RECEIVER_SHORT.decode()), 1)

    def test_the_text_report_names_the_path_not_a_hidraw_node(self):  # R2
        with windows(FakeHidBackend(g733())):
            text = photon_enumerate.format_text(photon_enumerate.enumerate_devices())
        self.assertIn("G733 Gaming Headset (046d:0afe)", text)
        self.assertIn("path: \\\\?\\HID#VID_046D&PID_0AFE", text)

    def test_all_includes_every_collection(self):  # R2
        with windows(FakeHidBackend(g733(), *noise())):
            devices = photon_enumerate.enumerate_devices(include_all=True)
        self.assertEqual(sum(len(d["interfaces"]) for d in devices), 5)

    def test_report_ids_follow_the_vendor_usage_pages(self):
        self.assertEqual(host.infer_report_ids(0xFF00, 1), (0x10,))
        self.assertEqual(host.infer_report_ids(0xFF00, 2), (0x11,))
        self.assertEqual(host.infer_report_ids(0xFF43, 0x0602), (0x11,))
        self.assertEqual(host.infer_report_ids(0x0C, 1), ())

    def test_the_receiver_channel_rule_differs_by_platform_only(self):  # R16
        with mock.patch.object(sys, "platform", "linux"):
            self.assertTrue(host.is_hidpp_channel({0x10, 0x11, 0x20}))
            self.assertFalse(host.is_hidpp_channel({0x11}))
        with mock.patch.object(sys, "platform", "win32"):
            self.assertTrue(host.is_hidpp_channel({0x11}))
            self.assertFalse(host.is_hidpp_channel({0x10}))


class WindowsTransportTests(unittest.TestCase):
    def test_open_session_does_not_require_a_file_system_node(self):
        backend = FakeHidBackend(g733(), keyboard(open_error=OSError("open failed")))
        with windows(backend):
            with HidTransport().open_session(G733_PATH.decode()) as session:
                self.assertEqual(session.path, G733_PATH.decode())
            with self.assertRaises(HidTransportError) as raised:
                HidTransport().open_session(KEYBOARD_LONG.decode())
        self.assertEqual(raised.exception.status, "transport_error")
        self.assertIn("held by another program", str(raised.exception))
        self.assertEqual(backend.endpoints[G733_PATH].opened, 1)

    def test_probe_open_close_opens_and_closes_a_windows_path(self):
        with windows(FakeHidBackend(g733())):
            result = HidTransport().probe_open_close(G733_PATH)
        self.assertEqual(result.status, "opened")


class DefaultConfigPathTests(unittest.TestCase):
    def test_windows_default_is_under_program_data(self):  # R13
        with mock.patch.object(sys, "platform", "win32"):
            path = host.default_config_path({"ProgramData": r"D:\Data"})
            fallback = host.default_config_path({})
        self.assertEqual(path.name, "config.toml")
        self.assertEqual(path.parent.name, "Photon")
        self.assertTrue(str(path).replace("/", "\\").endswith(r"D:\Data\Photon\config.toml"))
        self.assertTrue(str(fallback).replace("/", "\\").endswith(r"C:\ProgramData\Photon\config.toml"))

    def test_linux_default_is_unchanged(self):  # R13, R16
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(host.default_config_path(), Path("/etc/photon/config.toml"))

    def test_config_module_default_matches_the_host(self):  # R13
        self.assertEqual(config.DEFAULT_CONFIG_PATH, host.default_config_path())

    def test_a_missing_configuration_gives_the_default_color(self):  # R13
        with tempfile.TemporaryDirectory() as directory:
            loaded = config.load_config(Path(directory) / "Photon" / "config.toml")
        self.assertEqual(config.format_color(loaded.color), "#8B5CF6")


if __name__ == "__main__":
    unittest.main()
