# Contributing to Photon

Thanks for your interest. Photon is a small project: discussion happens in
[issues](https://github.com/jstmichel/photon/issues) before code.

## How work flows: small verified slices

1. **Idea** — open an issue with the *Idea or new hardware* template (label `idea`). Nothing
   is built from an idea alone.
2. **Slice** — once an idea is chosen, it gets a document in [docs/slices/](docs/slices/): the
   goal, what is verified on hardware and what is still an assumption, and a clear stopping
   point. [docs/PLAN.md](docs/PLAN.md) holds the overall design.
3. **Code and tests** — each slice is implemented with its tests, then committed. Hardware
   observations go into the slice document, not into unexplained constants.

Bugs use the *Bug* template (label `bug`); a fix comes with a test that fails without it.

## Hardware rules

Photon writes to real devices, some of them over SMBus. These rules are not negotiable:

- Never assume a USB interface, feature index, report size or SMBus address: resolve and
  verify it on the device at runtime, and refuse anything that does not match.
- Read-only probes come first. A command that changes RGB names its exact target.
- Never scan or write arbitrary SMBus addresses.
- Apply once, then close the device. No polling loops.

## Building and testing

```sh
python3 tools/build_bundle.py
build/venv/bin/python -m unittest discover -s tests -p 'test_*.py'
```

The build creates `build/venv` with the pinned `requirements-build.txt`, then `dist/photon`.
Every test must pass, as in CI. Tests never touch real things: HID transports, sysfs trees,
SMBus access and `systemctl` are faked, and installation tests write into temporary folders.

## Conventions

- **Language**: code, comments, commit messages and documentation in neutral English.
- **Commits**: [Conventional Commits](https://www.conventionalcommits.org)
  (`feat:`, `fix:`, `docs:`, `build:`, `ci:`, `test:`, `refactor:`, `chore:`), with a scope
  when it helps (`fix(g502): …`, `feat(service): …`). The body says why.
- **Style**: Python 3.11 or newer, standard library first; follow the surrounding files.
- **Personal data**: no real serial numbers or host names in code, tests, documents or
  issues; use made-up values.

## Pull requests

Keep a pull request to one topic, link its issue, and say what was verified on hardware.
CI runs the tests and builds the bundle for every pull request.
