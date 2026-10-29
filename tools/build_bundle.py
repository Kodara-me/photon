#!/usr/bin/env python3
"""Build the standalone Photon executable with a local PyInstaller venv."""

from __future__ import annotations

import hashlib
import io
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


WINDOWS = sys.platform == "win32"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build"
# The venv layout and the executable name depend on the host.
VENV_PYTHON = BUILD_ROOT / "venv" / ("Scripts/python.exe" if WINDOWS else "bin/python")
REQUIREMENTS = PROJECT_ROOT / "requirements-build.txt"
DIST_ROOT = PROJECT_ROOT / "dist"
PYINSTALLER_WORK = BUILD_ROOT / "pyinstaller"

# PawnIO's signed Intel i801 SMBus module, from a pinned PawnIO.Modules release. The
# SHA-256 of the module is recorded here; the build refuses any other content.
PAWNIO_MODULES_RELEASE = "0.2.11"
PAWNIO_MODULES_URL = (
    "https://github.com/namazso/PawnIO.Modules/releases/download/"
    f"{PAWNIO_MODULES_RELEASE}/release_{PAWNIO_MODULES_RELEASE.replace('.', '_')}.zip"
)
PAWNIO_MODULE_NAME = "SmbusI801.bin"
PAWNIO_MODULE_SHA256 = "a0f7d066e7efda28c0e754c1f52dbd8dc280d388ba8575b514a80cb67490530c"
PAWNIO_ROOT = BUILD_ROOT / "pawnio"


def run(*command: str) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def verify_pawnio_module(module: bytes, expected_sha256: str = PAWNIO_MODULE_SHA256) -> bytes:
    """Return the module only when its SHA-256 matches the recorded one."""
    actual = hashlib.sha256(module).hexdigest()
    if actual != expected_sha256:
        raise RuntimeError(
            f"{PAWNIO_MODULE_NAME} checksum mismatch: expected {expected_sha256}, got {actual}; "
            "refusing to bundle it"
        )
    return module


def fetch_pawnio_module(opener=urllib.request.urlopen, destination: Path = PAWNIO_ROOT) -> Path:
    """Download the pinned release, check the i801 module and write it for bundling."""
    with opener(PAWNIO_MODULES_URL, timeout=60) as response:
        archive = response.read()
    with zipfile.ZipFile(io.BytesIO(archive)) as release:
        module = verify_pawnio_module(release.read(PAWNIO_MODULE_NAME))
    destination.mkdir(parents=True, exist_ok=True)
    path = destination / PAWNIO_MODULE_NAME
    path.write_bytes(module)
    return path


def platform_arguments() -> list[str]:
    """PyInstaller options for the hidapi backend and event source of the host."""
    if WINDOWS:
        return ["--collect-all", "hid", "--add-data", f"{PAWNIO_ROOT / PAWNIO_MODULE_NAME};pawnio"]
    return [
        "--collect-all", "hidraw",
        "--collect-all", "pyudev",
        "--exclude-module", "pyudev.glib",
        "--exclude-module", "pyudev.pyqt4",
        "--exclude-module", "pyudev.pyqt5",
        "--exclude-module", "pyudev.pyside",
        "--exclude-module", "pyudev.pyside6",
        "--exclude-module", "pyudev.wx",
    ]


def main() -> int:
    if WINDOWS:
        print(f"fetching {PAWNIO_MODULE_NAME} from PawnIO.Modules {PAWNIO_MODULES_RELEASE}")
        fetch_pawnio_module()
    if not VENV_PYTHON.exists():
        run(sys.executable, "-m", "venv", str(BUILD_ROOT / "venv"))
    run(str(VENV_PYTHON), "-m", "pip", "install", "--requirement", str(REQUIREMENTS))
    run(str(VENV_PYTHON), "-c", "import hid" if WINDOWS else "import hidraw, pyudev")
    run(
        str(VENV_PYTHON),
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--name",
        "photon",
        "--distpath",
        str(DIST_ROOT),
        "--workpath",
        str(PYINSTALLER_WORK / "work"),
        "--specpath",
        str(PYINSTALLER_WORK / "spec"),
        "--paths",
        str(PROJECT_ROOT),
        "--collect-submodules",
        "photon",
        "--collect-submodules",
        "tools",
        *platform_arguments(),
        str(PROJECT_ROOT / "photon" / "__main__.py"),
    )
    bundle = DIST_ROOT / ("photon.exe" if WINDOWS else "photon")
    if not bundle.is_file():
        raise RuntimeError(f"PyInstaller did not produce {bundle}")
    print(f"built {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
