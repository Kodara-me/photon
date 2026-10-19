"""Install and manage the root-owned Photon systemd service."""

from __future__ import annotations

import argparse
import importlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .config import DEFAULT_COLOR_HEX, DEFAULT_CONFIG_PATH


UNIT_NAME = "photon.service"
INSTALL_DIRECTORY = Path("/usr/local/lib/photon")
INSTALLED_EXECUTABLE = INSTALL_DIRECTORY / "photon"
COMMAND_PATH = Path("/usr/local/bin/photon")
UNIT_PATH = Path("/etc/systemd/system") / UNIT_NAME
CONFIG_PATH = DEFAULT_CONFIG_PATH

# Installation layout of the project's former name, migrated by ``install``.
LEGACY_UNIT_NAME = "kira-lights.service"
LEGACY_INSTALL_DIRECTORY = Path("/usr/local/lib/kira-lights")
LEGACY_INSTALLED_EXECUTABLE = LEGACY_INSTALL_DIRECTORY / "kira-lights"
LEGACY_COMMAND_PATH = Path("/usr/local/bin/kira-lights")
LEGACY_UNIT_PATH = Path("/etc/systemd/system") / LEGACY_UNIT_NAME
LEGACY_CONFIG_PATH = Path("/etc/kira-lights/config.toml")


def check_dependencies() -> int:
    """Check runtime requirements without opening devices or changing the host."""
    failures = []
    if sys.platform != "linux":
        failures.append("Linux is required")
    if not shutil.which("systemctl") or not Path("/run/systemd/system").is_dir():
        failures.append("systemd must be installed and running as the system init")
    for name in ("hidraw", "pyudev"):
        try:
            module = importlib.import_module(name)
            if name == "pyudev":
                module.Context()  # Load libudev without probing or opening devices.
        except (ImportError, OSError, RuntimeError) as exc:
            failures.append(f"{name} runtime unavailable: {exc}")
    for failure in failures:
        print(f"missing: {failure}", file=sys.stderr)
    if failures:
        print("The bundle includes Python, hidapi and pyudev. The host must provide "
              "libudev (libudev1 on Debian/Ubuntu; systemd-libs on Fedora).", file=sys.stderr)
    else:
        print("Runtime dependencies available: Linux, systemd, hidapi and libudev.")
    if not list(Path("/dev").glob("i2c-*")):
        print("RAM prerequisite: no /dev/i2c-* nodes found. The host needs i2c-dev, "
              "the SMBus adapter driver and kernel-bound spd5118 hubs. "
              "No kernel modules or configuration were changed.")
    print("The service runs as root for hidraw and SMBus access. "
          "Hardware compatibility is verified separately by targeted probes.")
    return 1 if failures else 0


def unit_contents() -> str:
    return f"""[Unit]
Description=Photon RGB controller
After=local-fs.target systemd-udevd.service
Wants=systemd-udevd.service

[Service]
Type=simple
ExecStart={COMMAND_PATH} monitor --config {CONFIG_PATH}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""


def _write_file(path: Path, contents: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False, encoding="utf-8") as temporary:
        temporary.write(contents)
        temporary_path = Path(temporary.name)
    temporary_path.chmod(mode)
    temporary_path.replace(path)


def _copy_executable(source: Path) -> None:
    INSTALL_DIRECTORY.mkdir(parents=True, exist_ok=True)
    temporary = INSTALL_DIRECTORY / ".photon.new"
    shutil.copy2(source, temporary)
    temporary.chmod(0o755)
    temporary.replace(INSTALLED_EXECUTABLE)


def _is_managed_command_link() -> bool:
    try:
        return COMMAND_PATH.is_symlink() and os.readlink(COMMAND_PATH) == str(INSTALLED_EXECUTABLE)
    except OSError:
        return False


def _validate_command_path() -> None:
    if COMMAND_PATH.exists() or COMMAND_PATH.is_symlink():
        if not _is_managed_command_link():
            raise RuntimeError(f"refusing to replace existing command path {COMMAND_PATH}")


def _install_command_link() -> None:
    _validate_command_path()
    COMMAND_PATH.parent.mkdir(parents=True, exist_ok=True)
    if COMMAND_PATH.exists() or COMMAND_PATH.is_symlink():
        return
    COMMAND_PATH.symlink_to(INSTALLED_EXECUTABLE)


def _migrate_legacy_install() -> None:
    """Replace a kira-lights installation, keeping its color configuration."""
    if LEGACY_CONFIG_PATH.is_file() and not CONFIG_PATH.exists():
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(LEGACY_CONFIG_PATH, CONFIG_PATH)
        print(f"Copied {LEGACY_CONFIG_PATH} to {CONFIG_PATH}; the original is kept.")
    if LEGACY_UNIT_PATH.exists():
        _systemctl("disable", "--now", LEGACY_UNIT_NAME)
        LEGACY_UNIT_PATH.unlink()
        print(f"Stopped and removed {LEGACY_UNIT_NAME}.")
    try:
        legacy_link = LEGACY_COMMAND_PATH.is_symlink() and os.readlink(LEGACY_COMMAND_PATH) == str(
            LEGACY_INSTALLED_EXECUTABLE
        )
    except OSError:
        legacy_link = False
    if legacy_link:
        LEGACY_COMMAND_PATH.unlink()
    if LEGACY_INSTALL_DIRECTORY.exists():
        shutil.rmtree(LEGACY_INSTALL_DIRECTORY)


def _systemctl(*arguments: str, check: bool = True) -> int:
    completed = subprocess.run(["systemctl", *arguments], check=False)
    if check and completed.returncode:
        raise RuntimeError(f"systemctl {' '.join(arguments)} failed with exit code {completed.returncode}")
    return completed.returncode


def _require_root() -> None:
    if os.geteuid() != 0:
        raise RuntimeError("this operation requires root; run it with sudo")


def _is_bundle(executable: Path) -> bool:
    return bool(getattr(sys, "frozen", False)) and executable.is_file()


def install(executable: Path) -> None:
    _require_root()
    if not _is_bundle(executable):
        raise RuntimeError("service install must be run from the PyInstaller bundle (dist/photon)")
    _validate_command_path()
    if check_dependencies():
        raise RuntimeError("resolve the reported dependencies before installing")
    _migrate_legacy_install()
    _copy_executable(executable)
    _install_command_link()
    if not CONFIG_PATH.exists():
        _write_file(CONFIG_PATH, f'color = "{DEFAULT_COLOR_HEX}"\n', 0o644)
    _write_file(UNIT_PATH, unit_contents(), 0o644)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", UNIT_NAME)
    # ``enable --now`` leaves an already-active unit running its old bundle.
    # Restart so this install path is also a reliable in-place upgrade.
    _systemctl("restart", UNIT_NAME)


def uninstall() -> None:
    _require_root()
    _systemctl("disable", "--now", UNIT_NAME, check=False)
    UNIT_PATH.unlink(missing_ok=True)
    if _is_managed_command_link():
        COMMAND_PATH.unlink()
    if INSTALL_DIRECTORY.exists():
        shutil.rmtree(INSTALL_DIRECTORY)
    _systemctl("daemon-reload")


def status() -> int:
    return _systemctl("status", "--no-pager", UNIT_NAME, check=False)


def restart() -> None:
    _require_root()
    _systemctl("restart", UNIT_NAME)


def main(argv: list[str] | None = None, *, executable: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("install", "uninstall", "status", "restart", "check"))
    args = parser.parse_args(argv)
    source = (executable or Path(sys.argv[0])).resolve()
    if args.action == "check":
        return check_dependencies()
    if args.action == "install":
        install(source)
    elif args.action == "uninstall":
        uninstall()
    elif args.action == "restart":
        restart()
    else:
        return status()
    return 0
