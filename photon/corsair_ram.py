"""Direct static-color support for the detected Corsair Vengeance DDR5 kit."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .i2c import I2cBus, I2cError

RAM_VENDOR = "Corsair"
RAM_PART_NUMBER = "CMH64GX5M2B5600C40"
RAM_LED_COUNT = 10
RAM_SPD_DRIVER = "spd5118"
RAM_CONTROLLER_OFFSET = -0x38
RAM_CONTROLLER_SIGNATURE = (0x1B, 0x04)
RAM_CONTROLLER_SIGNATURE_REGISTERS = (0x43, 0x44)
RAM_COLOR_COMMAND = 0x31


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


def discover_modules(
    bus_paths: list[str] | None = None,
    bus_factory=I2cBus,
    spd_root: str | Path = "/sys/bus/i2c/devices",
) -> list[CorsairRamModule]:
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
    with bus_factory(module.bus_path) as bus:
        bus.write_block(module.controller_address, RAM_COLOR_COMMAND, static_color_packet(color))
