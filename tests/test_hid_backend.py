"""Each platform enumerates and opens devices through its own hidapi module."""

import sys
import unittest
from unittest import mock

from photon import hid_transport, host
from tools import photon_enumerate


class HidBackendTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "the hidraw backend is Linux-only")
    def test_enumeration_and_open_use_hidraw_backend_on_linux(self):
        import hidraw

        self.assertIs(photon_enumerate.hid, hidraw)
        self.assertIs(hid_transport.HidTransport()._device_factory, hidraw.device)

    @unittest.skipUnless(sys.platform == "win32", "the hid backend is the Windows one")
    def test_enumeration_and_open_use_hid_backend_on_windows(self):
        import hid

        self.assertIs(photon_enumerate.hid, hid)
        self.assertIs(hid_transport.HidTransport()._device_factory, hid.device)

    def test_backend_module_is_chosen_by_platform(self):
        with mock.patch.object(sys, "platform", "win32"), mock.patch.object(host, "import_module") as load:
            host.load_hid_backend()
        load.assert_called_once_with("hid")
        with mock.patch.object(sys, "platform", "linux"), mock.patch.object(host, "import_module") as load:
            host.load_hid_backend()
        load.assert_called_once_with("hidraw")
