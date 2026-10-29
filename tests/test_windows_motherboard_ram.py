"""The motherboard and the Corsair RAM on Windows, against fakes (R2-R7, R15-R17).

No test opens real hardware, PawnIO or the SMBus mutex: a fake hidapi backend, fake
SMBIOS data and a fake PawnIO transport stand in. ``sys.platform`` is patched to
``win32`` so the same tests run on Linux and on Windows.
"""

import contextlib
import hashlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photon import __main__ as cli
from photon import corsair_ram, gigabyte_rgb, pawnio, windows_firmware
from photon.corsair_ram import (
    RAM_COLOR_COMMAND,
    RAM_CONTROLLER_SIGNATURE,
    RAM_PART_NUMBER,
    CorsairRamModule,
    discover_modules,
    set_module_color,
    static_color_packet,
)
from photon.pawnio import PawnIoSmbus, RamUnavailable, SmbusMutexBusy
from tools import build_bundle, photon_apply

BOARD_PATH = b"\\\\?\\HID#VID_048D&PID_5702&MI_00&Col02#7&1f&0&0001#{4d1e55b2-f16f-11cf-88cb-001111000030}"
BOARD_OTHER_COLLECTION = BOARD_PATH.replace(b"Col02", b"Col01")
RED = (0xFF, 0x00, 0x00)

HOST_REPLY = bytes.fromhex(
    "cc 01 00 07 03 05 05 00 00 00 00 00 49 54 35 37 "
    "30 31 2d 47 49 47 41 42 59 54 45 20 56 33 2e 35 "
    "2e 35 2e 30 00 00 00 00 00 01 02 00 02 00 01 00 "
    "02 00 01 00 00 01 02 00 00 01 01 57 00 00 00 00"
)


def board_entry(**overrides):
    entry = {
        "path": BOARD_PATH, "vendor_id": 0x048D, "product_id": 0x5702, "interface_number": 0,
        "usage_page": 0xFF89, "usage": 0x00CC, "serial_number": "", "product_string": "ITE Device(5702)",
    }
    return {**entry, **overrides}


class FakeIteDevice:
    def __init__(self, backend):
        self.backend = backend

    def open_path(self, path):
        if self.backend.open_error:
            raise self.backend.open_error
        self.backend.opened.append(path)

    def close(self):
        self.backend.closed += 1

    def send_feature_report(self, data):
        self.backend.sent.append(bytes(data))
        return len(data)

    def get_feature_report(self, report_id, length):
        return list(self.backend.reply)

    def get_report_descriptor(self):
        return self.backend.descriptor


class FakeIteBackend:
    """Stands in for the ``hid`` module with one ITE controller."""

    def __init__(self, *entries, reply=HOST_REPLY, descriptor=b"", open_error=None):
        self.entries = list(entries)
        self.reply = reply
        self.descriptor = descriptor
        self.open_error = open_error
        self.opened, self.sent, self.closed = [], [], 0

    def enumerate(self, vendor_id=0, product_id=0):
        return [dict(e) for e in self.entries]

    def device(self):
        return FakeIteDevice(self)

    def lighting_reports(self):
        return [r for r in self.sent if r[1] != 0x60]


@contextlib.contextmanager
def windows(backend=None, board="Z790 AORUS ELITE AX", parts=(RAM_PART_NUMBER,), bus=None, library=True):
    """Run as Windows with the fake hidapi backend, SMBIOS data and PawnIO transport."""
    factory = (lambda path: bus) if bus is not None else None
    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(sys, "platform", "win32"))
        stack.enter_context(mock.patch("photon.gigabyte_rgb.load_hid_backend", return_value=backend))
        stack.enter_context(mock.patch("photon.gigabyte_rgb.time.sleep"))
        stack.enter_context(mock.patch("photon.windows_firmware.base_board_product", return_value=board))
        stack.enter_context(mock.patch("photon.windows_firmware.memory_part_numbers", return_value=list(parts)))
        stack.enter_context(mock.patch("photon.pawnio.find_library", return_value=Path("PawnIOLib.dll") if library else None))
        stack.enter_context(mock.patch("photon.pawnio.windows_bus_factory", factory or pawnio.windows_bus_factory))
        yield


class MotherboardTests(unittest.TestCase):
    def apply(self, backend, **kwargs):
        with windows(backend, **kwargs):
            gigabyte_rgb.apply_static_color(RED)

    def test_applies_all_eight_slots_on_the_verified_identity(self):  # R3
        backend = FakeIteBackend(board_entry())
        self.apply(backend)
        reports = backend.lighting_reports()
        self.assertEqual([r[1] for r in reports], [0x32, *range(0x20, 0x28), 0x28])
        self.assertEqual(struct.unpack_from("<I", reports[-1], 2)[0], 0xFF)
        self.assertEqual(backend.sent[0][:3], bytes((0xCC, 0x60, 0)))  # information query first
        self.assertEqual(backend.opened, [BOARD_PATH])
        self.assertEqual(backend.closed, 1)

    def test_refuses_a_different_board_before_opening_anything(self):  # R3
        backend = FakeIteBackend(board_entry())
        with self.assertRaisesRegex(RuntimeError, "verified Z790 AORUS ELITE AX"):
            self.apply(backend, board="Z690 AORUS ELITE")
        self.assertEqual((backend.opened, backend.sent), ([], []))

    def test_refuses_a_different_vid_pid_interface_or_usage_page(self):  # R3
        for change in (
            {"vendor_id": 0x048E}, {"product_id": 0x5701}, {"interface_number": 1},
            {"usage_page": 0xFF00}, {"usage": 0x0010},
        ):
            with self.subTest(change=change):
                backend = FakeIteBackend(board_entry(**change))
                with self.assertRaises(RuntimeError):
                    self.apply(backend)
                self.assertEqual((backend.opened, backend.sent), ([], []))

    def test_refuses_when_two_collections_match(self):  # R3
        backend = FakeIteBackend(board_entry(), board_entry(path=BOARD_OTHER_COLLECTION))
        with self.assertRaisesRegex(RuntimeError, "found 2"):
            self.apply(backend)
        self.assertEqual(backend.sent, [])

    def test_refuses_a_different_information_reply_and_sends_no_lighting_report(self):  # R3
        for position, value in ((56, 0x99), (4, 9), (12, ord("X")), (1, 7)):
            with self.subTest(position=position):
                reply = bytearray(HOST_REPLY)
                reply[position] = value
                backend = FakeIteBackend(board_entry(), reply=bytes(reply))
                with self.assertRaisesRegex(RuntimeError, "differs from the verified host probe"):
                    self.apply(backend)
                self.assertEqual(backend.lighting_reports(), [])
                self.assertEqual(backend.closed, 1)

    def test_refuses_a_short_or_misframed_information_reply(self):  # R3
        for reply in (HOST_REPLY[:20], b"\x01" + HOST_REPLY[1:]):
            backend = FakeIteBackend(board_entry(), reply=reply)
            with self.assertRaisesRegex(RuntimeError, "unexpected ITE controller information report"):
                self.apply(backend)
            self.assertEqual(backend.lighting_reports(), [])

    def test_refuses_an_exposed_descriptor_that_differs(self):  # R3
        backend = FakeIteBackend(board_entry(), descriptor=b"\x06\x00\xff")
        with self.assertRaisesRegex(RuntimeError, "descriptor differs"):
            self.apply(backend)
        self.assertEqual((backend.sent, backend.closed), ([], 1))

    def test_accepts_the_known_descriptor_when_exposed(self):  # R3
        for descriptor in (gigabyte_rgb.EXPECTED_DESCRIPTOR, gigabyte_rgb.FEATURE_COLLECTION_DESCRIPTOR):
            backend = FakeIteBackend(board_entry(), descriptor=descriptor)
            self.apply(backend)
            self.assertEqual(len(backend.lighting_reports()), 10)

    def test_a_held_controller_is_reported_unavailable(self):  # R3, R14
        backend = FakeIteBackend(board_entry(), open_error=OSError("open failed"))
        with self.assertRaisesRegex(RuntimeError, "held by another program"):
            self.apply(backend)

    def test_probe_reads_the_information_without_any_lighting_report(self):  # R2
        backend = FakeIteBackend(board_entry())
        with windows(backend):
            info = gigabyte_rgb.read_controller_info()
        self.assertEqual(info["description"], "IT5701-GIGABYTE V3.5.5.0")
        self.assertEqual(info["board"], "Z790 AORUS ELITE AX")
        self.assertEqual(backend.lighting_reports(), [])

    def test_commands_keep_the_linux_options_and_output(self):  # R2
        backend = FakeIteBackend(board_entry())
        out = io.StringIO()
        with windows(backend), contextlib.redirect_stdout(out):
            self.assertEqual(cli.main(["motherboard", "--color", "#ff0000"]), 0)
            self.assertEqual(cli.main(["probe", "motherboard", "--json"]), 0)
        text = out.getvalue()
        self.assertTrue(text.startswith("applied #FF0000 to motherboard/fan RGB (8 slots)\n"))
        self.assertEqual(json.loads(text.split("\n", 1)[1])["firmware"], "3.5.5.0")


class FakeSmbus:
    """A fake PawnIO bus: two DDR5 modules (hubs 0x51 and 0x53) and a stray device."""

    def __init__(self, controllers=(0x19, 0x1B), hubs=(0x51, 0x53), signature=RAM_CONTROLLER_SIGNATURE):
        self.controllers, self.hubs, self.signature = set(controllers), set(hubs), signature
        self.reads: list[tuple[int, int]] = []
        self.writes: list[tuple[int, int, bytes]] = []
        self.path = pawnio.SMBUS_BUS_PATH

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read_register(self, address, register):
        self.reads.append((address, register))
        if address in self.hubs:
            return 0
        if address in self.controllers:
            return {0x43: self.signature[0], 0x44: self.signature[1]}.get(register, 0)
        raise OSError("no device")

    def write_block(self, address, command, payload):
        self.writes.append((address, command, payload))


class RamTests(unittest.TestCase):
    def test_applies_to_each_module_that_answers_the_signature(self):  # R4
        bus = FakeSmbus()
        with windows(bus=bus):
            modules = discover_modules()
            for module in modules:
                set_module_color(module, RED)
        self.assertEqual(
            modules,
            [CorsairRamModule("smbus-i801", 0x51, 0x19), CorsairRamModule("smbus-i801", 0x53, 0x1B)],
        )
        self.assertEqual(
            bus.writes,
            [(0x19, RAM_COLOR_COMMAND, static_color_packet(RED)), (0x1B, RAM_COLOR_COMMAND, static_color_packet(RED))],
        )

    def test_a_part_number_that_does_not_match_reads_nothing(self):  # R4, R5
        bus = FakeSmbus()
        with windows(bus=bus, parts=("CMK32GX5M2B5600C36", "")):
            self.assertEqual(discover_modules(), [])
        self.assertEqual((bus.reads, bus.writes), ([], []))

    def test_a_controller_with_another_signature_is_not_a_module_and_is_never_written(self):  # R4, R5
        bus = FakeSmbus(signature=(0x00, 0x00))
        with windows(bus=bus):
            self.assertEqual(discover_modules(), [])
        self.assertEqual(bus.writes, [])

    def test_only_the_spd_hubs_and_paired_controllers_are_read(self):  # R5
        bus = FakeSmbus()
        with windows(bus=bus):
            discover_modules()
        allowed = set(range(0x50, 0x58)) | {hub - 0x38 for hub in range(0x50, 0x58)}
        self.assertTrue({address for address, _ in bus.reads} <= allowed)
        self.assertEqual({a for a, _ in bus.reads} & set(range(0x50, 0x58)), set(range(0x50, 0x58)))
        self.assertEqual({r for a, r in bus.reads if a < 0x20}, {0x43, 0x44})

    def test_the_guard_refuses_a_read_outside_the_allowed_addresses(self):  # R5
        guard = corsair_ram.GuardedSmbus(FakeSmbus())
        for address in (0x03, 0x17, 0x20, 0x4F, 0x58, 0x77):
            with self.assertRaisesRegex(RuntimeError, "refusing to read"):
                guard.read_register(address, 0x00)

    def test_the_guard_refuses_a_write_without_a_just_verified_signature(self):  # R5
        bus = FakeSmbus()
        guard = corsair_ram.GuardedSmbus(bus)
        with self.assertRaisesRegex(RuntimeError, "not verified"):
            guard.write_block(0x19, RAM_COLOR_COMMAND, b"\x00")
        self.assertTrue(guard.verify_controller(0x19))
        guard.write_block(0x19, RAM_COLOR_COMMAND, b"\x00")
        bus.signature = (0, 0)  # the controller stops answering: the verification is dropped
        self.assertFalse(guard.verify_controller(0x19))
        with self.assertRaisesRegex(RuntimeError, "not verified"):
            guard.write_block(0x19, RAM_COLOR_COMMAND, b"\x00")
        self.assertFalse(guard.verify_controller(0x60))  # not a paired controller address
        self.assertEqual(len(bus.writes), 1)

    def test_a_write_to_an_address_that_is_no_longer_verified_is_refused(self):  # R5
        bus = FakeSmbus(signature=(0, 0))
        with windows(bus=bus), self.assertRaisesRegex(RuntimeError, "no longer answers"):
            set_module_color(CorsairRamModule("smbus-i801", 0x51, 0x19), RED)
        self.assertEqual(bus.writes, [])

    def test_a_module_outside_the_pairing_is_never_written(self):  # R5
        bus = FakeSmbus()
        with windows(bus=bus), self.assertRaises(RuntimeError):
            set_module_color(CorsairRamModule("smbus-i801", 0x60, 0x28), RED)
        self.assertEqual(bus.writes, [])

    def test_missing_pawnio_is_reported_unavailable_with_the_reason(self):  # R6
        with windows(library=False):
            with self.assertRaisesRegex(RamUnavailable, "PawnIO is not installed"):
                discover_modules()

    def test_a_missing_pawnio_leaves_the_other_devices_applied(self):  # R6
        backend = FakeIteBackend(board_entry())
        with windows(backend, library=False), \
                mock.patch.object(photon_apply, "_apply_g733", return_value="G733 (2 zone(s))"), \
                mock.patch.object(photon_apply, "_apply_g502", side_effect=RuntimeError("absent")), \
                mock.patch.object(photon_apply, "_apply_keyboard", side_effect=RuntimeError("absent")):
            result = photon_apply.apply_available(RED)
        self.assertEqual(result.applied, ("G733 (2 zone(s))", "Gigabyte motherboard/fan RGB (8 slots)"))
        ram = [item for item in result.failures if item.startswith("Corsair RAM")]
        self.assertEqual(len(ram), 1)
        self.assertIn("PawnIO is not installed", ram[0])
        self.assertEqual(len(backend.lighting_reports()), 10)

    def test_not_elevated_is_reported_unavailable_with_the_reason(self):  # R6
        with windows(), mock.patch("photon.pawnio.is_elevated", return_value=False), \
                mock.patch("photon.pawnio.SmbusMutex") as mutex:
            with self.assertRaisesRegex(RamUnavailable, "not elevated"):
                pawnio.open_smbus_library()
        mutex.assert_not_called()

    def test_the_ram_command_reports_the_reason_and_exits_nonzero(self):  # R2, R6
        with windows(library=False), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, "PawnIO is not installed"):
                cli.main(["ram", "--color", "#ff0000"])


class FakeLibrary:
    def __init__(self):
        self.calls = []

    def execute(self, name, cells, out_cells):
        self.calls.append((name, list(cells), out_cells))
        return [0x42] + [0] * (out_cells - 1)

    def close(self):
        pass


class FakeMutex:
    def __init__(self, busy=False):
        self.busy, self.held, self.entries = busy, False, 0

    def __enter__(self):
        if self.busy:
            raise SmbusMutexBusy("the SMBus is held by another program (Global\\Access_SMBUS.HTP.Method not released in 5 s)")
        self.held = True
        self.entries += 1
        return self

    def __exit__(self, *_args):
        self.held = False

    def close(self):
        pass


class PawnIoTransportTests(unittest.TestCase):
    def test_each_transaction_holds_the_smbus_mutex(self):  # R7
        mutex = FakeMutex()
        library = FakeLibrary()
        held_during = []
        original = library.execute
        library.execute = lambda *a: (held_during.append(mutex.held), original(*a))[1]
        bus = PawnIoSmbus(library=library, mutex=mutex)
        self.assertEqual(bus.read_register(0x51, 0x00), 0x42)
        bus.write_block(0x19, RAM_COLOR_COMMAND, static_color_packet(RED))
        self.assertEqual(held_during, [True, True])
        self.assertEqual((mutex.entries, mutex.held), (2, False))

    def test_a_mutex_that_is_not_released_in_time_reports_the_ram_unavailable(self):  # R7
        library = FakeLibrary()
        bus = PawnIoSmbus(library=library, mutex=FakeMutex(busy=True))
        with self.assertRaisesRegex(RamUnavailable, "held by another program"):
            bus.read_register(0x51, 0x00)
        self.assertEqual(library.calls, [])  # no access while another program holds the bus

    def test_a_busy_mutex_stops_the_discovery_and_reaches_apply_as_unavailable(self):  # R7
        bus = PawnIoSmbus(library=FakeLibrary(), mutex=FakeMutex(busy=True))
        with windows(bus=bus):
            result = photon_apply.apply_available(RED, only="ram")
        self.assertEqual(result.applied, ())
        self.assertIn("held by another program", result.failures[0])

    def test_the_transfer_carries_address_direction_command_and_block(self):  # R4
        library = FakeLibrary()
        bus = PawnIoSmbus(library=library, mutex=FakeMutex())
        bus.write_block(0x19, 0x31, b"\x01\x02")
        name, cells, out_cells = library.calls[0]
        self.assertEqual(name, b"ioctl_smbus_xfer")
        self.assertEqual(cells[:4], [0x19, pawnio.SMBUS_WRITE, 0x31, pawnio.SMBUS_BLOCK_DATA])
        self.assertEqual(cells[4].to_bytes(8, "little")[:3], b"\x02\x01\x02")
        self.assertEqual(len(cells), pawnio.XFER_HEADER_CELLS + pawnio.XFER_DATA_CELLS)
        with self.assertRaises(ValueError):
            bus.write_block(0x19, 0x31, bytes(33))

    def test_the_library_is_looked_up_only_in_the_pawnio_install_folder(self):  # R15
        with tempfile.TemporaryDirectory() as root:
            env = {"ProgramFiles": root}
            self.assertIsNone(pawnio.find_library(env))
            (Path(root) / "PawnIO").mkdir()
            (Path(root) / "PawnIO" / "PawnIOLib.dll").write_bytes(b"")
            self.assertEqual(pawnio.find_library(env), Path(root) / "PawnIO" / "PawnIOLib.dll")

    def test_no_code_path_installs_updates_or_removes_a_driver(self):  # R15
        root = Path(__file__).resolve().parents[1]
        forbidden = ("CreateServiceW", "DeleteService", "StartServiceW", "pnputil", "sc.exe", "InstallHinfSection")
        for source in [*(root / "photon").glob("*.py"), *(root / "tools").glob("*.py")]:
            text = source.read_text(encoding="utf-8")
            for word in forbidden:
                if source.name == "service.py":
                    continue  # the Photon service itself, not a driver
                self.assertNotIn(word, text, f"{source.name}: {word}")
        self.assertFalse(any(name.startswith(("install", "update", "remove")) for name in dir(pawnio)))


class SmbiosTests(unittest.TestCase):
    @staticmethod
    def memory_device(part_index, strings):
        formatted = bytearray(0x22)
        formatted[0], formatted[1] = 17, 0x22
        formatted[0x1A] = part_index
        return bytes(formatted) + b"".join(s.encode() + b"\x00" for s in strings) + b"\x00"

    def test_reads_the_part_numbers_of_the_populated_memory_devices(self):  # R4
        table = (
            self.memory_device(2, ["Corsair", RAM_PART_NUMBER + "  "])
            + self.memory_device(0, ["NO DIMM"])
            + self.memory_device(1, ["CMK32GX5M2B5600C36"])
            + bytes([127, 4, 0, 0, 0, 0])
        )
        self.assertEqual(windows_firmware.parse_memory_part_numbers(table), [RAM_PART_NUMBER, "CMK32GX5M2B5600C36"])

    def test_a_truncated_table_does_not_raise(self):  # R4
        self.assertEqual(windows_firmware.parse_memory_part_numbers(b"\x11\x22\x00"), [])


class BuildTests(unittest.TestCase):
    def test_the_build_accepts_the_module_with_the_recorded_checksum(self):  # R15
        data = b"module"
        expected = hashlib.sha256(data).hexdigest()
        self.assertEqual(build_bundle.verify_pawnio_module(data, expected), data)

    def test_the_build_fails_on_a_module_checksum_mismatch(self):  # R15
        with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
            build_bundle.verify_pawnio_module(b"tampered")

    def test_fetch_refuses_a_tampered_module_and_writes_nothing(self):  # R15
        import zipfile

        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as release:
            release.writestr(build_bundle.PAWNIO_MODULE_NAME, b"tampered")

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return None

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "pawnio"
            with self.assertRaisesRegex(RuntimeError, "checksum mismatch"):
                build_bundle.fetch_pawnio_module(lambda url, timeout: Response(archive.getvalue()), target)
            self.assertFalse(target.exists())

    def test_the_module_comes_from_the_pinned_release(self):  # R15
        self.assertIn(f"/download/{build_bundle.PAWNIO_MODULES_RELEASE}/", build_bundle.PAWNIO_MODULES_URL)
        self.assertRegex(build_bundle.PAWNIO_MODULE_SHA256, r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
