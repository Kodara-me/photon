import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photon.corsair_ram import (
    RAM_COLOR_COMMAND,
    RAM_CONTROLLER_SIGNATURE,
    CorsairRamModule,
    discover_modules,
    set_module_color,
    static_color_packet,
)


class FakeBus:
    instances = []

    def __init__(self, path):
        self.path = path
        self.writes = []
        self.closed = False
        self.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def read_register(self, address, register):
        if address == 0x19 and register == 0x43:
            return RAM_CONTROLLER_SIGNATURE[0]
        if address == 0x19 and register == 0x44:
            return RAM_CONTROLLER_SIGNATURE[1]
        return 0

    def write_block(self, address, command, payload):
        self.writes.append((address, command, payload))


class CorsairRamTests(unittest.TestCase):
    def setUp(self):
        # The sysfs discovery under test is the Linux one, whatever host runs the suite.
        patcher = mock.patch.object(sys, "platform", "linux")
        patcher.start()
        self.addCleanup(patcher.stop)
        FakeBus.instances = []
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.spd_root = Path(self.directory.name)
        slot = self.spd_root / "15-0051"
        slot.mkdir()
        (slot / "name").write_text("spd5118\n", encoding="utf-8")

    def test_discovers_kernel_bound_spd_hub_and_ddr5_controller(self):
        modules = discover_modules(["/dev/i2c-15"], bus_factory=FakeBus, spd_root=self.spd_root)
        self.assertEqual(modules, [CorsairRamModule("/dev/i2c-15", 0x51, 0x19)])

    def test_static_packet_sets_all_ten_leds_and_crc(self):
        self.assertEqual(
            static_color_packet((0x8B, 0x5C, 0xF6)).hex(" "),
            "0a 8b 5c f6 8b 5c f6 8b 5c f6 8b 5c f6 8b 5c f6 "
            "8b 5c f6 8b 5c f6 8b 5c f6 8b 5c f6 8b 5c f6 ff",
        )

    def test_writes_one_all_led_static_packet_per_module(self):
        module = CorsairRamModule("/dev/i2c-15", 0x51, 0x19)
        set_module_color(module, (0x8B, 0x5C, 0xF6), bus_factory=FakeBus)
        self.assertEqual(
            FakeBus.instances[0].writes,
            [(0x19, RAM_COLOR_COMMAND, static_color_packet((0x8B, 0x5C, 0xF6)))],
        )
