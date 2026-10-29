"""Install and manage the Photon Windows service (Service Control Manager, LocalSystem).

Everything that talks to the Service Control Manager goes through ``ServiceManager``, so
tests drive the install, upgrade and removal logic with a fake and never touch the real
one. ``pywin32`` is imported only where a real service is created or hosted.
"""

from __future__ import annotations

import logging
import logging.handlers
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Protocol

from .config import DEFAULT_COLOR_HEX
from .host import is_windows, program_data_folder, program_files_folders


LOGGER = logging.getLogger(__name__)

SERVICE_NAME = "Photon"
DISPLAY_NAME = "Photon RGB controller"
DESCRIPTION = "Applies the configured RGB color to the supported devices at boot, on resume and on reconnect."
# Automatic start, not delayed: a delayed start would run about two minutes after boot and
# miss the sign-in screen (R19). PlugPlay is the only dependency; PawnIO is optional.
DEPENDENCIES = ("PlugPlay",)
RESTART_DELAY_MS = 5000
RESTART_ATTEMPTS = 3
FAILURE_RESET_SECONDS = 24 * 60 * 60

PBT_APMRESUMEAUTOMATIC = 0x12

ERROR_SERVICE_DOES_NOT_EXIST = 1060
ERROR_SERVICE_NOT_ACTIVE = 1062
ERROR_FAILED_SERVICE_CONTROLLER_CONNECT = 1063

SYSTEM_SID = "*S-1-5-18"
ADMINISTRATORS_SID = "*S-1-5-32-544"
USERS_SID = "*S-1-5-32-545"

ELEVATION_MESSAGE = (
    "this operation requires an elevated prompt; run it from a Command Prompt or PowerShell "
    "opened with Run as administrator"
)


@dataclass(frozen=True)
class Layout:
    """Where the service lives: the executable in Program Files, the data in ProgramData."""

    install_directory: Path
    data_directory: Path

    @property
    def executable(self) -> Path:
        return self.install_directory / "photon.exe"

    @property
    def config_path(self) -> Path:
        return self.data_directory / "config.toml"


def default_layout() -> Layout:
    folders = program_files_folders()
    program_files = folders[0] if folders else Path(r"C:\Program Files")
    return Layout(program_files / "Photon", program_data_folder() / "Photon")


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    display_name: str
    description: str
    binary_path: str
    start_type: str  # "auto"
    delayed_start: bool
    account: str
    dependencies: tuple[str, ...]
    restart_attempts: int
    restart_delay_ms: int


def service_spec(layout: Layout) -> ServiceSpec:
    return ServiceSpec(
        name=SERVICE_NAME,
        display_name=DISPLAY_NAME,
        description=DESCRIPTION,
        binary_path=f'"{layout.executable}" monitor --config "{layout.config_path}"',
        start_type="auto",
        delayed_start=False,
        account="LocalSystem",
        dependencies=DEPENDENCIES,
        restart_attempts=RESTART_ATTEMPTS,
        restart_delay_ms=RESTART_DELAY_MS,
    )


class ServiceManager(Protocol):
    def state(self) -> str | None:
        """``running``, ``stopped``, ``start_pending``... or None when not installed."""

    def create(self, spec: ServiceSpec) -> None: ...

    def update(self, spec: ServiceSpec) -> None: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def delete(self) -> None: ...


def _winerror(exc: BaseException) -> int | None:
    value = getattr(exc, "winerror", None)
    if value is None and exc.args and isinstance(exc.args[0], int):
        value = exc.args[0]
    return value


class Win32ServiceManager:
    """The real Service Control Manager, through ``pywin32``'s ``win32service``."""

    def __init__(self, name: str = SERVICE_NAME, *, win32service: Any = None,
                 sleep: Callable[[float], None] = time.sleep, wait_seconds: float = 30.0):
        self.name = name
        self._w = win32service or import_module("win32service")
        self._sleep = sleep
        self._wait_seconds = wait_seconds

    def _states(self) -> dict[int, str]:
        w = self._w
        return {
            w.SERVICE_RUNNING: "running",
            w.SERVICE_STOPPED: "stopped",
            w.SERVICE_START_PENDING: "start_pending",
            w.SERVICE_STOP_PENDING: "stop_pending",
            w.SERVICE_PAUSED: "paused",
        }

    def _open(self, access: int):
        """(manager handle, service handle or None when the service does not exist)."""
        w = self._w
        scm = w.OpenSCManager(None, None, w.SC_MANAGER_CONNECT)
        try:
            return scm, w.OpenService(scm, self.name, access)
        except Exception as exc:
            if _winerror(exc) == ERROR_SERVICE_DOES_NOT_EXIST:
                return scm, None
            w.CloseServiceHandle(scm)
            raise

    def _query(self, handle) -> str:
        code = self._w.QueryServiceStatus(handle)[1]
        return self._states().get(code, f"state {code}")

    def _wait_for(self, handle, wanted: str) -> None:
        deadline = time.monotonic() + self._wait_seconds
        while self._query(handle) != wanted:
            if time.monotonic() > deadline:
                raise RuntimeError(f"the {self.name} service did not become {wanted} in time")
            self._sleep(0.5)

    def state(self) -> str | None:
        w = self._w
        scm, handle = self._open(w.SERVICE_QUERY_STATUS)
        try:
            return None if handle is None else self._query(handle)
        finally:
            if handle is not None:
                w.CloseServiceHandle(handle)
            w.CloseServiceHandle(scm)

    def _configure(self, handle, spec: ServiceSpec) -> None:
        w = self._w
        w.ChangeServiceConfig2(handle, w.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, spec.delayed_start)
        w.ChangeServiceConfig2(handle, w.SERVICE_CONFIG_DESCRIPTION, spec.description)
        w.ChangeServiceConfig2(handle, w.SERVICE_CONFIG_FAILURE_ACTIONS, {
            "ResetPeriod": FAILURE_RESET_SECONDS,
            "RebootMsg": "",
            "Command": "",
            "Actions": [(w.SC_ACTION_RESTART, spec.restart_delay_ms)] * spec.restart_attempts,
        })
        # Also restart when the service stops itself with an error, not only when it crashes.
        w.ChangeServiceConfig2(handle, w.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG, True)

    def create(self, spec: ServiceSpec) -> None:
        w = self._w
        scm = w.OpenSCManager(None, None, w.SC_MANAGER_CONNECT | w.SC_MANAGER_CREATE_SERVICE)
        try:
            handle = w.CreateService(
                scm, spec.name, spec.display_name, w.SERVICE_ALL_ACCESS, w.SERVICE_WIN32_OWN_PROCESS,
                w.SERVICE_AUTO_START, w.SERVICE_ERROR_NORMAL, spec.binary_path,
                None, 0, list(spec.dependencies), None, None,  # no account given: LocalSystem
            )
            try:
                self._configure(handle, spec)
            finally:
                w.CloseServiceHandle(handle)
        finally:
            w.CloseServiceHandle(scm)

    def update(self, spec: ServiceSpec) -> None:
        w = self._w
        scm, handle = self._open(w.SERVICE_ALL_ACCESS)
        if handle is None:
            w.CloseServiceHandle(scm)
            raise RuntimeError(f"the {self.name} service is not installed")
        try:
            w.ChangeServiceConfig(
                handle, w.SERVICE_WIN32_OWN_PROCESS, w.SERVICE_AUTO_START, w.SERVICE_ERROR_NORMAL,
                spec.binary_path, None, 0, list(spec.dependencies), spec.account, "", spec.display_name,
            )
            self._configure(handle, spec)
        finally:
            w.CloseServiceHandle(handle)
            w.CloseServiceHandle(scm)

    def start(self) -> None:
        w = self._w
        scm, handle = self._open(w.SERVICE_START | w.SERVICE_QUERY_STATUS)
        if handle is None:
            w.CloseServiceHandle(scm)
            raise RuntimeError(f"the {self.name} service is not installed")
        try:
            if self._query(handle) != "running":
                w.StartService(handle, None)
                self._wait_for(handle, "running")
        finally:
            w.CloseServiceHandle(handle)
            w.CloseServiceHandle(scm)

    def stop(self) -> None:
        w = self._w
        scm, handle = self._open(w.SERVICE_STOP | w.SERVICE_QUERY_STATUS)
        if handle is None:
            w.CloseServiceHandle(scm)
            return
        try:
            if self._query(handle) != "stopped":
                try:
                    w.ControlService(handle, w.SERVICE_CONTROL_STOP)
                except Exception as exc:
                    if _winerror(exc) != ERROR_SERVICE_NOT_ACTIVE:
                        raise
                self._wait_for(handle, "stopped")
        finally:
            w.CloseServiceHandle(handle)
            w.CloseServiceHandle(scm)

    def delete(self) -> None:
        w = self._w
        scm, handle = self._open(w.DELETE)
        if handle is None:
            w.CloseServiceHandle(scm)
            return
        try:
            w.DeleteService(handle)
        finally:
            w.CloseServiceHandle(handle)
            w.CloseServiceHandle(scm)


def is_elevated() -> bool:
    from .pawnio import is_elevated as pawnio_is_elevated

    return pawnio_is_elevated()


def _require_elevated(elevated: Callable[[], bool]) -> None:
    if not elevated():
        raise RuntimeError(ELEVATION_MESSAGE)


def secure_data_directory(directory: Path, run: Callable[..., Any] = subprocess.run) -> None:
    """Create ``%ProgramData%\\Photon`` with writes limited to Administrators and SYSTEM.

    The configuration is read by a LocalSystem service, so it must not be writable by
    ordinary users. Inheritance from ProgramData is cut; Users keep read access only.
    """
    directory.mkdir(parents=True, exist_ok=True)
    run(
        ["icacls", str(directory), "/inheritance:r",
         "/grant:r", f"{SYSTEM_SID}:(OI)(CI)F", f"{ADMINISTRATORS_SID}:(OI)(CI)F", f"{USERS_SID}:(OI)(CI)RX"],
        check=True, capture_output=True,
    )


def _is_bundle(executable: Path) -> bool:
    return bool(getattr(sys, "frozen", False)) and executable.is_file()


def _copy_executable(source: Path, layout: Layout) -> None:
    layout.install_directory.mkdir(parents=True, exist_ok=True)
    target = layout.executable
    if target.exists() and source.resolve() == target.resolve():
        return  # running the installed copy: nothing to replace
    temporary = layout.install_directory / ".photon.new"
    shutil.copy2(source, temporary)
    temporary.replace(target)


def check_dependencies(*, importer: Callable[[str], Any] = import_module,
                       elevated: Callable[[], bool] | None = None,
                       library_finder: Callable[[], Path | None] | None = None,
                       module_path: Callable[[], Path] | None = None) -> int:
    """Report the prerequisites without opening devices or changing anything."""
    from . import pawnio

    failures = []
    if not is_windows():
        failures.append("Windows is required")
    for name in ("hid", "win32service", "servicemanager"):
        try:
            importer(name)
        except ImportError as exc:
            failures.append(f"{name} unavailable: {exc}")
    for failure in failures:
        print(f"missing: {failure}", file=sys.stderr)
    if not failures:
        print("Runtime dependencies available: Windows, hidapi and pywin32.")
    is_admin = (elevated or is_elevated)()
    if not is_admin:
        print("This prompt is not elevated: install, uninstall and restart need an elevated prompt.")
    library = (library_finder or pawnio.find_library)()
    if library is None:
        print("RAM prerequisite: PawnIO is not installed (PawnIOLib.dll not found). Only the RAM is "
              "disabled; every other device works. Install PawnIO yourself from https://pawnio.eu "
              "to drive the RAM. Photon never installs a driver.")
    else:
        module = (module_path or pawnio.module_blob_path)()
        if module.is_file():
            print(f"PawnIO found at {library}; the i801 module is available.")
        else:
            print(f"PawnIO found at {library}, but the i801 module is missing ({module}); "
                  "the RAM is disabled.")
    print("The service runs as LocalSystem, starting at boot before any sign-in. "
          "Nothing was changed.")
    return 1 if failures else 0


def install(executable: Path, *, manager: ServiceManager, layout: Layout,
            elevated: Callable[[], bool] = is_elevated, run: Callable[..., Any] = subprocess.run,
            is_bundle: Callable[[Path], bool] = _is_bundle) -> None:
    _require_elevated(elevated)
    if not is_bundle(executable):
        raise RuntimeError("service install must be run from the standalone executable (dist\\photon.exe)")
    secure_data_directory(layout.data_directory, run)
    if not layout.config_path.exists():
        layout.config_path.write_text(f'color = "{DEFAULT_COLOR_HEX}"\n', encoding="utf-8")
        print(f"Created {layout.config_path} with the default color.")
    installed = manager.state() is not None
    if installed:
        manager.stop()  # a running service holds its executable open
    _copy_executable(executable, layout)
    spec = service_spec(layout)
    if installed:
        manager.update(spec)
    else:
        manager.create(spec)
    manager.start()
    print(f"{'Upgraded' if installed else 'Installed'} and started the {SERVICE_NAME} service "
          f"({layout.executable}).")


def uninstall(*, manager: ServiceManager, layout: Layout,
              elevated: Callable[[], bool] = is_elevated) -> None:
    _require_elevated(elevated)
    if manager.state() is not None:
        manager.stop()
        manager.delete()
    if layout.install_directory.exists():
        shutil.rmtree(layout.install_directory)
    print(f"Removed the {SERVICE_NAME} service and its executable; kept {layout.config_path}.")


def status(*, manager: ServiceManager) -> int:
    state = manager.state()
    if state is None:
        print(f"The {SERVICE_NAME} service is not installed.")
        return 4
    print(f"The {SERVICE_NAME} service is {state.replace('_', ' ')}.")
    return 0 if state == "running" else 3


def restart(*, manager: ServiceManager, elevated: Callable[[], bool] = is_elevated) -> None:
    _require_elevated(elevated)
    if manager.state() is None:
        raise RuntimeError(f"the {SERVICE_NAME} service is not installed; run 'photon service install'")
    manager.stop()
    manager.start()
    print(f"Restarted the {SERVICE_NAME} service.")


def main(action: str, executable: Path, *, manager: ServiceManager | None = None,
         layout: Layout | None = None, elevated: Callable[[], bool] = is_elevated) -> int:
    if action == "check":
        return check_dependencies(elevated=elevated)
    manager = manager or Win32ServiceManager()
    layout = layout or default_layout()
    if action == "install":
        install(executable, manager=manager, layout=layout, elevated=elevated)
    elif action == "uninstall":
        uninstall(manager=manager, layout=layout, elevated=elevated)
    elif action == "restart":
        restart(manager=manager, elevated=elevated)
    else:
        return status(manager=manager)
    return 0


class ServiceHost:
    """Runs the monitor for the service and turns power events into resume applies (R20)."""

    def __init__(self, config_path: str, monitor_factory: Callable[[str, threading.Event], Any] | None = None,
                 *, configure_logging: bool = False):
        if monitor_factory is None:
            from .windows_monitor import build_monitor as monitor_factory
        self._config_path = config_path
        self._configure_logging = configure_logging
        self._monitor_factory = monitor_factory
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._monitor: Any = None
        self._resume_pending = False

    def run(self) -> None:
        if self._configure_logging:
            _configure_logging(self._config_path, hosted=True)
        monitor = self._monitor_factory(self._config_path, self._stop_event)
        with self._lock:
            self._monitor = monitor
            pending, self._resume_pending = self._resume_pending, False
        if pending:
            monitor.post_resume()
        if self._stop_event.is_set():
            monitor.stop()
        monitor.run()

    def stop(self) -> None:
        self._stop_event.set()
        with self._lock:
            monitor = self._monitor
        if monitor is not None:
            monitor.stop()

    def power_event(self, event_type: int) -> None:
        if event_type != PBT_APMRESUMEAUTOMATIC:
            return
        with self._lock:
            monitor = self._monitor
            if monitor is None:
                self._resume_pending = True
                return
        monitor.post_resume()


def make_service_class(framework: type, win32service: Any, host_factory: Callable[[], ServiceHost]) -> type:
    """The ``pywin32`` service class, a thin shell over ``ServiceHost``."""

    class PhotonService(framework):  # type: ignore[misc, valid-type]
        _svc_name_ = SERVICE_NAME
        _svc_display_name_ = DISPLAY_NAME
        _svc_description_ = DESCRIPTION

        def __init__(self, args):
            super().__init__(args)
            self.host = host_factory()

        def GetAcceptedControls(self):
            # Power events are what tells the service the machine resumed (Fast Startup too).
            return super().GetAcceptedControls() | win32service.SERVICE_ACCEPT_POWEREVENT

        def SvcDoRun(self):
            try:
                self.host.run()
            except Exception:
                LOGGER.exception("the monitor stopped with an error")
                raise

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.host.stop()

        def SvcOtherEx(self, control, event_type, data):
            if control == win32service.SERVICE_CONTROL_POWEREVENT:
                self.host.power_event(event_type)

    return PhotonService


def _configure_logging(config_path: str, hosted: bool) -> None:
    handlers: list[logging.Handler] = []
    if hosted:
        # Session 0 has no console: keep a small rotating log beside the configuration.
        try:
            log_path = Path(config_path).parent / "photon.log"
            handlers.append(logging.handlers.RotatingFileHandler(
                log_path, maxBytes=256 * 1024, backupCount=2, encoding="utf-8"))
        except OSError:
            pass
    if not handlers:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s",
                        handlers=handlers, force=True)


def run_hosted(config_path: str, *, modules: SimpleNamespace | None = None,
               foreground: Callable[[str], int] | None = None) -> int:
    """Host the service when the Service Control Manager started this process.

    From a console the dispatcher refuses the connection (error 1063), and the monitor runs
    in the foreground instead.
    """
    if modules is None:
        modules = SimpleNamespace(
            servicemanager=import_module("servicemanager"),
            win32serviceutil=import_module("win32serviceutil"),
            win32service=import_module("win32service"),
        )
    if foreground is None:
        from .windows_monitor import run_foreground as foreground
    service_class = make_service_class(
        modules.win32serviceutil.ServiceFramework, modules.win32service, lambda: ServiceHost(config_path, configure_logging=True))
    try:
        modules.servicemanager.Initialize()
        modules.servicemanager.PrepareToHostSingle(service_class)
        modules.servicemanager.StartServiceCtrlDispatcher()
        return 0
    except Exception as exc:
        if _winerror(exc) != ERROR_FAILED_SERVICE_CONTROLLER_CONNECT:
            raise
    _configure_logging(config_path, hosted=False)
    return foreground(config_path)
