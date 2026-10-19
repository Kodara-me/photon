import unittest
from unittest import mock

from photon import __main__


class ControllerCliTests(unittest.TestCase):
    def test_motherboard_apply_forwards_options_without_zone_arguments(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_motherboard.main", command):
            result = __main__.main(["apply", "--only", "motherboard", "--color", "#8b5cf6", "--trace"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--color", "#8b5cf6", "--trace"])

    def test_motherboard_probe_forwards_read_only_options(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_motherboard.probe_main", command):
            result = __main__.main(["probe", "motherboard", "--json", "--trace"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--json", "--trace"])
    def test_apply_forwards_color_options_to_all_device_command(self):
        command = mock.Mock(return_value=0)
        with mock.patch.object(__main__, "_device_main", return_value=command) as device_main:
            result = __main__.main(["apply", "--only", "ram", "--color", "#ff0000", "--trace"])
        self.assertEqual(result, 0)
        device_main.assert_called_once_with("ram")
        command.assert_called_once_with(["--color", "#ff0000", "--trace"])

    def test_apply_only_g502_does_not_require_zone_arguments(self):
        command = mock.Mock(return_value=0)
        with mock.patch.object(__main__, "_device_main", return_value=command) as device_main:
            result = __main__.main(["apply", "--only", "g502", "--color", "#ff0000"])
        self.assertEqual(result, 0)
        device_main.assert_called_once_with("g502")
        command.assert_called_once_with(["--color", "#ff0000"])

    def test_targeted_zone_is_forwarded(self):
        command = mock.Mock(return_value=0)
        with mock.patch.object(__main__, "_device_main", return_value=command):
            __main__.main(["keyboard", "--zone", "1"])
        command.assert_called_once_with(["--zone", "1"])

    def test_default_device_apply_uses_all_zones(self):
        command = mock.Mock(return_value=0)
        with mock.patch.object(__main__, "_device_main", return_value=command):
            __main__.main(["g502"])
        command.assert_called_once_with([])

    def test_ram_probe_delegates_without_writing(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_ram_probe.main", command):
            result = __main__.main(["probe", "ram", "--json"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--json"])

    def test_g502_probe_forwards_read_only_options(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_g502_probe.main", command):
            result = __main__.main(["probe", "g502", "--json", "--trace"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--json", "--trace"])

    def test_monitor_forwards_an_optional_config_path(self):
        command = mock.Mock(return_value=0)
        with mock.patch("photon.monitor.main", command):
            result = __main__.main(["monitor", "--config", "/tmp/photon.toml"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--config", "/tmp/photon.toml"])

    def test_service_delegates_to_the_service_controller(self):
        command = mock.Mock(return_value=0)
        with mock.patch("photon.service.main", command):
            result = __main__.main(["service", "status"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["status"])

    def test_g733_event_probe_forwards_duration_without_writing(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_g733_events.main", command):
            result = __main__.main(["probe", "g733-events", "--seconds", "45"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--seconds", "45.0"])

    def test_g733_feature_probe_delegates_without_writing(self):
        command = mock.Mock(return_value=0)
        with mock.patch("tools.photon_g733_features.main", command):
            result = __main__.main(["probe", "g733", "--json"])
        self.assertEqual(result, 0)
        command.assert_called_once_with(["--json"])
