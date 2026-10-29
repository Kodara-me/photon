"""Direct static-color support for the detected Corsair Vengeance DDR5 kit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .host import is_windows
from .i2c import I2cBus, I2cError

RAM_VENDOR = "Corsair"
RAM_PART_NUMBER = "CMH64GX5M2B5600C40"
RAM_LED_COUNT = 10
RAM_SPD_DRIVER = "spd5118"
RAM_CONTROLLER_OFFSET = -0x38
RAM_CONTROLLER_SIGNATURE = (0x1B, 0x04)
RAM_CONTROLLER_SIGNATURE_REGISTERS = (0x43, 0x44)
RAM_COLOR_COMMAND = 0x31
# Windows has no spd5118 binding: only these addresses are ever read, and only a
# controller whose signature was just verified is ever written.
SPD_HUB_ADDRESSES = range(0x50, 0x58)
CONTROLLER_ADDRESSES = frozenset(hub + RAM_CONTROLLER_OFFSET for hub in SPD_HUB_ADDRESSES)
SPD_PROBE_REGISTER = 0x00


@dataclass(frozen=True)
class CorsairRamModule:
    bus_path: str
    spd_address: int
    controller_address: int
    part_number: str = RAM_PART_NUMBER
    led_count: int = RAM_LED_COUNT

    @property
    def name(self) -> str:
        return f"Corsair Vengeance RGB DDR5 at {self.bus_path}:0x{self.controller_address:02x}"


def _crc8(data: bytes) -> int:
    crc = 0
    for value in data:
        crc ^= value
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def static_color_packet(color: tuple[int, int, int]) -> bytes:
    r, g, b = color
    payload = bytes([RAM_LED_COUNT]) + bytes((r, g, b)) * RAM_LED_COUNT
    return payload + bytes([_crc8(payload)])


def _controller_matches(bus: I2cBus, address: int) -> bool:
    try:
        return tuple(bus.read_register(address, register) for register in RAM_CONTROLLER_SIGNATURE_REGISTERS) == RAM_CONTROLLER_SIGNATURE
    except I2cError:
        return False


def _spd_slots(spd_root: str | Path = "/sys/bus/i2c/devices") -> list[tuple[str, int]]:
    slots: list[tuple[str, int]] = []
    for device in sorted(Path(spd_root).glob("*-00*")):
        try:
            bus_number, address_text = device.name.split("-", 1)
            address = int(address_text, 16)
            driver = (device / "name").read_text().strip()
        except (OSError, ValueError):
            continue
        if driver == RAM_SPD_DRIVER:
            slots.append((f"/dev/i2c-{bus_number}", address))
    return slots


class GuardedSmbus:
    """Limits a bus to the addresses Photon may touch on Windows (R5).

    Reads are allowed at the SPD hubs and their paired controllers. A write is allowed
    only at a controller whose signature this guard has just read and matched.
    """

    def __init__(self, bus):
        self._bus = bus
        self._verified: set[int] = set()

    def read_register(self, address: int, register: int) -> int:
        if address not in CONTROLLER_ADDRESSES and address not in SPD_HUB_ADDRESSES:
            raise RuntimeError(f"refusing to read SMBus address 0x{address:02x}: outside the SPD hubs and controllers")
        return self._bus.read_register(address, register)

    def verify_controller(self, address: int) -> bool:
        self._verified.discard(address)
        if address in CONTROLLER_ADDRESSES and _controller_matches(self, address):
            self._verified.add(address)
        return address in self._verified

    def write_block(self, address: int, command: int, payload: bytes) -> None:
        if address not in self._verified:
            raise RuntimeError(f"refusing to write SMBus address 0x{address:02x}: controller signature not verified")
        self._bus.write_block(address, command, payload)


def _windows_bus_factory():
    from .pawnio import windows_bus_factory

    return windows_bus_factory


def _discover_windows(bus_factory=None, part_numbers=None) -> list[CorsairRamModule]:
    from .pawnio import SMBUS_BUS_PATH

    if part_numbers is None:
        from .windows_firmware import memory_part_numbers as part_numbers
    # The part number comes from SMBIOS first: nothing is read from the bus without it.
    if RAM_PART_NUMBER not in part_numbers():
        return []
    factory = bus_factory or _windows_bus_factory()
    modules: list[CorsairRamModule] = []
    with factory(SMBUS_BUS_PATH) as raw_bus:
        bus = GuardedSmbus(raw_bus)
        for hub in SPD_HUB_ADDRESSES:
            try:
                bus.read_register(hub, SPD_PROBE_REGISTER)  # a hub that answers is populated
            except (I2cError, OSError):
                continue
            controller = hub + RAM_CONTROLLER_OFFSET
            try:
                matches = bus.verify_controller(controller)
            except (I2cError, OSError):
                matches = False
            if matches:
                modules.append(CorsairRamModule(SMBUS_BUS_PATH, hub, controller))
    return modules


def discover_modules(
    bus_paths: list[str] | None = None,
    bus_factory=I2cBus,
    spd_root: str | Path = "/sys/bus/i2c/devices",
    part_numbers=None,
) -> list[CorsairRamModule]:
    if is_windows():
        return _discover_windows(None if bus_factory is I2cBus else bus_factory, part_numbers)
    modules: list[CorsairRamModule] = []
    slots = _spd_slots(spd_root)
    if bus_paths is not None:
        slots = [slot for slot in slots if slot[0] in bus_paths]
    for bus_path, spd_address in slots:
        try:
            with bus_factory(bus_path) as bus:
                controller_address = spd_address + RAM_CONTROLLER_OFFSET
                if 0x03 <= controller_address <= 0x77 and _controller_matches(bus, controller_address):
                    candidate = CorsairRamModule(bus_path, spd_address, controller_address)
                    if candidate not in modules:
                        modules.append(candidate)
        except (I2cError, OSError):
            continue
    return modules


def set_module_color(module: CorsairRamModule, color: tuple[int, int, int], bus_factory=I2cBus) -> None:
    if is_windows():
        factory = _windows_bus_factory() if bus_factory is I2cBus else bus_factory
        with factory(module.bus_path) as raw_bus:
            bus = GuardedSmbus(raw_bus)
            if not bus.verify_controller(module.controller_address):
                raise RuntimeError(
                    f"RAM controller 0x{module.controller_address:02x} no longer answers the verified signature"
                )
            bus.write_block(module.controller_address, RAM_COLOR_COMMAND, static_color_packet(color))
        return
    with bus_factory(module.bus_path) as bus:
        bus.write_block(module.controller_address, RAM_COLOR_COMMAND, static_color_packet(color))
