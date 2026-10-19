# Slice 16 — Corsair Vengeance RGB DDR5 RAM

## Objective

Control the two exact Corsair Vengeance RGB DDR5 modules without OpenRGB or liquidctl at runtime.

## Confirmed hardware

| Module | Part number | SPD hub | RGB controller | LEDs |
|---|---|---:|---:|---:|
| 1 | `CMH64GX5M2B5600C40` | `0x51` | `0x19` | 10 |
| 2 | `CMH64GX5M2B5600C40` | `0x53` | `0x1b` | 10 |

The hubs are attached to the current Intel I801 SMBus (`/dev/i2c-15`). The bus number is not
persisted: discovery starts from the kernel's `spd5118` devices and derives the current `/dev/i2c-N`
path at runtime.

## Protocol and safety

Discovery is read-only. A module is accepted only when the paired controller answers
`0x43=0x1b` and `0x44=0x04`. Static color writes use SMBus block command `0x31` with a 32-byte
payload: LED count `0x0a`, ten RGB triples, then CRC-8 (polynomial `0x07`). No arbitrary SMBus
address scan or write is permitted.

## Commands

```bash
python3 tools/photon_ram_probe.py --json
python3 tools/photon_ram_color.py
python3 tools/photon_ram_color.py --color '#ff0000' --trace
```

Omitting `--color` uses the configured global color or the default, `#8B5CF6`. One packet is
sent to each verified module, setting all ten LEDs on that module.

## Hardware observation — 2026-08-07

The read-only probe confirmed both controller signatures. The first static-color test sent
`0x31` plus `0a` + ten `8b 5c f6` triples + CRC `ff` to controllers `0x19` and `0x1b`.
Visual confirmation is required before treating the RAM backend as complete.
