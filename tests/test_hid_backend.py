"""Keep enumeration and transport on the Linux hidraw backend."""

import unittest

import hidraw

from photon import hid_transport
from tools import photon_enumerate


class HidBackendTests(unittest.TestCase):
    def test_enumeration_and_open_use_hidraw_backend(self):
        self.assertIs(photon_enumerate.hid, hidraw)
        self.assertIs(hid_transport.HidTransport()._device_factory, hidraw.device)
