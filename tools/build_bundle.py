#!/usr/bin/env python3
"""Build the standalone Photon executable with a local PyInstaller venv."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUILD_ROOT = PROJECT_ROOT / "build"
VENV_PYTHON = BUILD_ROOT / "venv" / "bin" / "python"
REQUIREMENTS = PROJECT_ROOT / "requirements-build.txt"
DIST_ROOT = PROJECT_ROOT / "dist"
PYINSTALLER_WORK = BUILD_ROOT / "pyinstaller"


def run(*command: str) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> int:
    if not VENV_PYTHON.exists():
        run(sys.executable, "-m", "venv", str(BUILD_ROOT / "venv"))
    run(str(VENV_PYTHON), "-m", "pip", "install", "--requirement", str(REQUIREMENTS))
    run(str(VENV_PYTHON), "-c", "import hidraw, pyudev")
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
        "--collect-all",
        "hidraw",
        "--collect-all",
        "pyudev",
        "--exclude-module", "pyudev.glib",
        "--exclude-module", "pyudev.pyqt4",
        "--exclude-module", "pyudev.pyqt5",
        "--exclude-module", "pyudev.pyside",
        "--exclude-module", "pyudev.pyside6",
        "--exclude-module", "pyudev.wx",
        str(PROJECT_ROOT / "photon" / "__main__.py"),
    )
    bundle = DIST_ROOT / "photon"
    if not bundle.is_file():
        raise RuntimeError(f"PyInstaller did not produce {bundle}")
    print(f"built {bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
