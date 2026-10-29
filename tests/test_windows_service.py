"""The Windows service, its monitoring and its resume handling, against fakes (R8-R13, R15, R19, R20).

No test opens a device, PawnIO, the real Service Control Manager, the registry or the
configuration manager: a fake service manager, a fake ``win32service`` module, a fake
arrival source and fake power events stand in. Every test runs on Linux and on Windows.
"""

import contextlib
import io
import os
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from photon import host, monitor as photon_monitor, pawnio, receiver_notifications, service, windows_monitor, windows_service
from photon.monitor import DeviceMonitor, event_identity, target_for_event
from photon.windows_monitor import (
    ARRIVAL,
    Arrival,
    CmSubscription,
    WindowsMonitor,
    instance_id_from_link,
    parse_interface_arrival,
)
from photon.windows_service import Layout, ServiceHost, ServiceSpec, Win32ServiceManager

HID_CLASS = "{4d1e55b2-f16f-11cf-88cb-001111000030}"


def link(vid, pid, interface, instance="7&1a2b3c4d&0&0000"):
    return f"\\\\?\\HID#VID_{vid}&PID_{pid}&MI_{interface}#{instance}#{HID_CLASS}"


G733 = link("046D", "0AFE", "03")
G502_USB = link("046D", "C095", "02")
G502_USB_OTHER_INTERFACE = link("046D", "C095", "01", "7&99&0&0000")
G502_RECEIVER = link("046D", "C547", "02")
KEYBOARD = link("046D", "C339", "01")
MOTHERBOARD = link("048D", "5702", "00")
MOUSE_OF_SOMEONE_ELSE = link("1234", "ABCD", "00")


def usb_instance(vid_pid, number="5&2f&0&1"):
    return f"usb\\vid_{vid_pid[0]}&pid_{vid_pid[1]}\\{number}"


def resolver(mapping):
    """A fake configuration-manager lookup: HID interface link -> USB device instance."""
    return lambda path: mapping.get(path)


def ok(*names):
    return SimpleNamespace(applied=tuple(names), failures=())


def failed(reason="not ready"):
    return SimpleNamespace(applied=(), failures=(reason,))


class Recorder:
    """An apply function that records (target) and answers from a script or with success."""

    def __init__(self, script=None):
        self.calls = []
        self.script = script or {}

    def __call__(self, color, target):
        self.calls.append(target)
        answers = self.script.get(target)
        if answers:
            return answers.pop(0)
        return ok(target)


class FakeSubscription:
    def __init__(self, sink, order):
        self.sink, self.order = sink, order
        self.started = self.stopped = False

    def start(self):
        self.started = True
        self.order.append("subscribed")

    def stop(self):
        self.stopped = True


def make_monitor(apply, *, mapping=None, retry_delays=(), delays=None, **options):
    now = [100.0]
    device_monitor = DeviceMonitor(
        color=(1, 2, 3), apply=apply, retry_delays=retry_delays,
        sleep=(delays.append if delays is not None else (lambda _s: None)),
        clock=lambda: now[0], **options,
    )
    order = []
    subscriptions = []

    def subscribe(sink):
        subscription = FakeSubscription(sink, order)
        subscriptions.append(subscription)
        return subscription

    runner = WindowsMonitor(device_monitor, subscribe=subscribe, resolve_instance=resolver(mapping or {}))
    runner.order, runner.subscriptions, runner.now = order, subscriptions, now
    return runner


def run_with(runner, *events):
    for kind, payload in events:
        runner.events.put((kind, payload))
    runner.stop()
    runner.run()


class ArrivalSourceTests(unittest.TestCase):
    """R9: arrivals mapped to targets by VID:PID and debounced by USB device instance."""

    def test_a_supported_arrival_applies_to_its_target_and_an_unrelated_one_is_ignored(self):  # R9
        apply = Recorder()
        runner = make_monitor(apply)
        run_with(runner, (ARRIVAL, G733), (ARRIVAL, G502_RECEIVER), (ARRIVAL, KEYBOARD),
                 (ARRIVAL, MOTHERBOARD), (ARRIVAL, MOUSE_OF_SOMEONE_ELSE))
        startup = ["g733", "g502", "keyboard", "ram", "motherboard"]
        self.assertEqual(apply.calls, startup + ["g733", "g502", "keyboard", "motherboard"])

    def test_the_arrival_keeps_the_existing_retries(self):  # R9
        apply = Recorder({"g733": [ok("g733")] + [failed(), failed(), ok("g733")]})
        delays = []
        runner = make_monitor(apply, retry_delays=(0.5, 1.0, 2.0), delays=delays)
        run_with(runner, (ARRIVAL, G733))
        self.assertEqual(apply.calls.count("g733"), 4)  # one at startup, three for the arrival
        self.assertEqual(delays, [0.5, 1.0])

    def test_interfaces_of_one_physical_device_are_debounced_together(self):  # R9
        instance = usb_instance(("046d", "c095"))
        runner = make_monitor(Recorder(), mapping={G502_USB: instance, G502_USB_OTHER_INTERFACE: instance})
        apply = runner.monitor.apply
        run_with(runner, (ARRIVAL, G502_USB), (ARRIVAL, G502_USB_OTHER_INTERFACE))
        self.assertEqual(apply.calls.count("g502"), 2)  # startup + one arrival, not two

    def test_two_devices_of_one_model_are_not_merged(self):  # R9
        mapping = {G502_USB: usb_instance(("046d", "c095"), "5&1&0&1"),
                   G502_USB_OTHER_INTERFACE: usb_instance(("046d", "c095"), "5&2&0&2")}
        runner = make_monitor(Recorder(), mapping=mapping)
        run_with(runner, (ARRIVAL, G502_USB), (ARRIVAL, G502_USB_OTHER_INTERFACE))
        self.assertEqual(runner.monitor.apply.calls.count("g502"), 3)

    def test_an_arrival_after_the_debounce_window_applies_again(self):  # R9
        runner = make_monitor(Recorder(), mapping={G733: usb_instance(("046d", "0afe"))})
        runner.events.put((ARRIVAL, G733))
        runner.handle(*runner.events.get())
        runner.now[0] += 3.1
        runner.handle(ARRIVAL, G733)
        self.assertEqual(runner.monitor.apply.calls, ["g733", "g733"])

    def test_the_subscription_is_made_before_the_startup_apply(self):  # R9, R19
        order = []
        runner = make_monitor(lambda color, target: order.append(f"apply {target}") or ok(target))
        runner.order = order
        runner.subscriptions.clear()
        original = runner._subscribe

        def subscribe(sink):
            subscription = original(sink)
            subscription.order = order
            return subscription

        runner._subscribe = subscribe
        run_with(runner)
        self.assertEqual(order[0], "subscribed")
        self.assertEqual(order[1], "apply g733")
        self.assertTrue(runner.subscriptions[0].stopped)

    def test_an_arrival_during_the_startup_apply_is_applied_afterwards(self):  # R9, R19
        calls = []

        def apply(color, target):
            calls.append(target)
            if target == "g733":  # a device enumerated while the startup apply is still running
                runner.subscriptions[0].sink(KEYBOARD)
            if target == "motherboard":
                runner.stop()
            return ok(target)

        runner = make_monitor(apply)
        runner.run()
        self.assertEqual(calls[:5], ["g733", "g502", "keyboard", "ram", "motherboard"])
        self.assertEqual(calls[5:], ["keyboard"])

    def test_an_arrival_object_reads_like_a_udev_device(self):
        arrival = Arrival(G502_RECEIVER, resolver({G502_RECEIVER: "usb\\vid_046d&pid_c547\\5&1"}))
        self.assertEqual(target_for_event(arrival), "g502")
        self.assertEqual(event_identity(arrival), "usb\\vid_046d&pid_c547\\5&1")
        self.assertEqual(target_for_event(Arrival(MOTHERBOARD)), "motherboard")
        self.assertIsNone(target_for_event(Arrival(MOUSE_OF_SOMEONE_ELSE)))
        self.assertEqual(event_identity(Arrival(G733)), "usb:046d:0afe")  # lookup failed: model fallback

    def test_the_instance_is_not_looked_up_for_an_unrelated_device(self):
        lookup = mock.Mock(return_value=None)
        runner = make_monitor(Recorder())
        runner._resolve_instance = lookup
        run_with(runner, (ARRIVAL, MOUSE_OF_SOMEONE_ELSE))
        lookup.assert_not_called()

    def test_a_failing_event_does_not_stop_the_monitor(self):
        apply = Recorder()
        runner = make_monitor(apply)
        runner.monitor.handle_event = mock.Mock(side_effect=[RuntimeError("boom"), True])
        with self.assertLogs("photon.windows_monitor", level="ERROR"):
            run_with(runner, (ARRIVAL, G733), (ARRIVAL, KEYBOARD))
        self.assertEqual(runner.monitor.handle_event.call_count, 2)

    def test_the_symbolic_link_becomes_a_device_instance_id(self):
        self.assertEqual(instance_id_from_link(G502_USB), "HID\\VID_046D&PID_C095&MI_02\\7&1a2b3c4d&0&0000")


def event_data(link_text, *, filter_type=0, guid=bytes(16)):
    return struct.pack("<II", filter_type, 0) + guid + link_text.encode("utf-16-le") + b"\x00\x00"


class NotificationTests(unittest.TestCase):
    def test_an_interface_arrival_yields_its_symbolic_link(self):  # R9
        self.assertEqual(parse_interface_arrival(0, event_data(G733)), G733)

    def test_removals_and_other_filters_are_ignored(self):
        self.assertIsNone(parse_interface_arrival(1, event_data(G733)))
        self.assertIsNone(parse_interface_arrival(0, event_data(G733, filter_type=1)))
        self.assertIsNone(parse_interface_arrival(0, b"\x00" * 8))

    def test_the_subscription_registers_once_and_unregisters_once(self):
        received = []
        register = mock.Mock(return_value=("handle", "callback"))
        unregister = mock.Mock()
        subscription = CmSubscription(received.append, register=register, unregister=unregister)
        subscription.start()
        callback = register.call_args.args[0]
        callback(0, event_data(KEYBOARD))
        callback(1, event_data(G733))
        subscription.stop()
        subscription.stop()
        self.assertEqual(received, [KEYBOARD])
        unregister.assert_called_once_with("handle")

    def test_the_real_registration_targets_the_hid_interface_class(self):
        self.assertEqual(windows_monitor.GUID_DEVINTERFACE_HID, HID_CLASS.strip("{}"))

    @unittest.skipUnless(sys.platform == "win32", "the structure layout is the Windows one")
    def test_the_notification_filter_has_the_size_the_configuration_manager_expects(self):
        self.assertEqual(windows_monitor.ctypes.sizeof(windows_monitor._NotifyFilter), 416)


class ResumeTests(unittest.TestCase):
    """R20: a resume applies to every available device as at startup; arrivals after it still apply."""

    def test_a_resume_applies_to_every_device_as_at_startup(self):  # R20
        apply = Recorder()
        runner = make_monitor(apply)
        run_with(runner, (windows_monitor.RESUME, None))
        targets = ["g733", "g502", "keyboard", "ram", "motherboard"]
        self.assertEqual(apply.calls, targets + targets)

    def test_a_device_arriving_after_the_resume_is_still_applied(self):  # R20
        apply = Recorder()
        runner = make_monitor(apply, mapping={KEYBOARD: usb_instance(("046d", "c339"))})
        run_with(runner, (windows_monitor.RESUME, None), (ARRIVAL, KEYBOARD))
        self.assertEqual(apply.calls[-1], "keyboard")
        self.assertEqual(len(apply.calls), 11)

    def test_the_resume_applies_the_configured_color(self):  # R20
        colors = []
        runner = make_monitor(lambda color, target: colors.append(color) or ok(target))
        run_with(runner, (windows_monitor.RESUME, None))
        self.assertEqual(set(colors), {(1, 2, 3)})
        self.assertEqual(len(colors), 10)

    def test_a_resume_posted_from_the_power_event_reaches_the_monitor(self):  # R20
        apply = Recorder()
        runner = make_monitor(apply)
        runner.post_resume()
        runner.stop()
        runner.run()
        self.assertEqual(len(apply.calls), 10)

    def test_the_resume_is_logged(self):
        runner = make_monitor(Recorder())
        with self.assertLogs("photon.windows_monitor", level="INFO") as logs:
            run_with(runner, (windows_monitor.RESUME, None))
        self.assertTrue(any("resumed" in line for line in logs.output))


class LateRamTests(unittest.TestCase):
    """PawnIO can load after the service starts at boot: the RAM is retried later, bounded."""

    def monitor(self, script, **options):
        waits = []
        apply = Recorder(script)
        device_monitor = DeviceMonitor(
            color=(1, 2, 3), apply=apply, retry_delays=(), sleep=lambda _s: None,
            late_retry_delays=(5.0, 10.0, 20.0),
            late_wait=lambda delay: waits.append(delay) or False,
            start_thread=lambda run: run(), **options,
        )
        device_monitor.waits, device_monitor.recorder = waits, apply
        return device_monitor

    def test_the_ram_is_applied_when_pawnio_loads_late(self):
        device_monitor = self.monitor({"ram": [failed("PawnIO is not installed"), failed(), ok("ram")]})
        device_monitor.apply_startup()
        self.assertEqual(device_monitor.waits, [5.0, 10.0])
        self.assertEqual(device_monitor.recorder.calls.count("ram"), 3)

    def test_the_series_is_bounded_and_ends_with_a_warning(self):
        device_monitor = self.monitor({"ram": [failed()] * 10})
        with self.assertLogs("photon.monitor", level="WARNING") as logs:
            device_monitor.apply_startup("resume")
        self.assertEqual(device_monitor.waits, [5.0, 10.0, 20.0])
        self.assertEqual(device_monitor.recorder.calls.count("ram"), 4)
        self.assertTrue(any("gave up" in line for line in logs.output))

    def test_only_the_ram_is_retried_late(self):
        device_monitor = self.monitor({"g733": [failed()] * 10})
        device_monitor.apply_startup()
        self.assertEqual(device_monitor.waits, [])

    def test_a_resume_that_misses_the_ram_starts_a_new_series(self):
        device_monitor = self.monitor({"ram": [failed(), ok("ram"), failed(), ok("ram")]})
        device_monitor.apply_startup()
        device_monitor.apply_startup("resume")
        self.assertEqual(device_monitor.waits, [5.0, 5.0])

    def test_stopping_ends_the_series(self):
        device_monitor = self.monitor({"ram": [failed()] * 10})
        device_monitor.late_wait = lambda delay: True
        device_monitor.apply_startup()
        self.assertEqual(device_monitor.recorder.calls.count("ram"), 1)

    def test_a_running_series_is_not_doubled(self):
        started = []
        alive = SimpleNamespace(is_alive=lambda: True)
        device_monitor = self.monitor({"ram": [failed()] * 10})
        device_monitor.start_thread = lambda run: started.append(run) or alive
        device_monitor.apply_startup()
        device_monitor.apply_startup("resume")
        self.assertEqual(len(started), 1)

    def test_linux_has_no_late_series(self):  # R16
        starter = mock.Mock()
        device_monitor = DeviceMonitor(
            color=(1, 2, 3), apply=Recorder({"ram": [failed()]}), retry_delays=(), start_thread=starter)
        device_monitor.apply_startup()
        starter.assert_not_called()

    def test_the_late_wait_defaults_to_the_stop_event(self):
        stop = threading.Event()
        stop.set()
        device_monitor = DeviceMonitor(color=(1, 2, 3), apply=Recorder(), stop_event=stop)
        self.assertTrue(device_monitor._wait(60.0))


class ProductionWiringTests(unittest.TestCase):
    def test_the_monitor_uses_the_configured_color_and_one_stop_event(self):
        with tempfile.TemporaryDirectory() as root:
            config = Path(root) / "config.toml"
            config.write_text('color = "#102030"\n', encoding="utf-8")
            stop = threading.Event()
            runner = windows_monitor.build_monitor(str(config), stop)
        self.assertEqual(runner.monitor.color, (0x10, 0x20, 0x30))
        self.assertIs(runner.monitor.stop_event, stop)
        self.assertIs(runner.stop_event, stop)
        self.assertEqual(runner.monitor.late_retry_delays, photon_monitor.LATE_RETRY_DELAYS_SECONDS)

    def test_the_monitor_command_hosts_the_service_on_windows(self):
        with mock.patch.object(photon_monitor, "is_windows", return_value=True), \
                mock.patch("photon.windows_service.run_hosted", return_value=0) as hosted:
            self.assertEqual(photon_monitor.main(["--config", "C:\\ProgramData\\Photon\\config.toml"]), 0)
        hosted.assert_called_once_with("C:\\ProgramData\\Photon\\config.toml")

    def test_the_receiver_listens_on_the_short_report_collection_on_windows(self):  # R9
        devices = [{"vendor_id": "046d", "product_id": "c547", "interfaces": [
            {"hidapi_path": "short", "report_ids": (0x10,)}, {"hidapi_path": "long", "report_ids": (0x11,)}]}]
        with mock.patch.object(receiver_notifications, "is_windows", return_value=True):
            self.assertEqual(receiver_notifications.receiver_notification_paths(devices), ("short",))
        with mock.patch.object(receiver_notifications, "is_windows", return_value=False):
            self.assertEqual(receiver_notifications.receiver_notification_paths(devices), ())  # R16


class FakeServiceManager:
    """A fake Service Control Manager: records calls, keeps the installed spec and state."""

    def __init__(self, state=None):
        self._state = state
        self.spec = None
        self.calls = []

    def state(self):
        return self._state

    def create(self, spec):
        self.calls.append("create")
        self.spec, self._state = spec, "stopped"

    def update(self, spec):
        self.calls.append("update")
        self.spec = spec

    def start(self):
        self.calls.append("start")
        self._state = "running"

    def stop(self):
        self.calls.append("stop")
        if self._state is not None:
            self._state = "stopped"

    def delete(self):
        self.calls.append("delete")
        self._state = None


class ServiceInstallTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.layout = Layout(root / "Program Files" / "Photon", root / "ProgramData" / "Photon")
        self.source = root / "dist" / "photon.exe"
        self.source.parent.mkdir()
        self.source.write_bytes(b"photon 1")
        self.manager = FakeServiceManager()
        self.acl_calls = []

    def install(self, **options):
        defaults = dict(manager=self.manager, layout=self.layout, elevated=lambda: True,
                        run=lambda command, **kw: self.acl_calls.append(command),
                        is_bundle=lambda path: True)
        defaults.update(options)
        with contextlib.redirect_stdout(io.StringIO()):
            windows_service.install(self.source, **defaults)

    def test_install_creates_the_service_the_executable_and_the_configuration(self):  # R8, R13
        self.install()
        self.assertEqual(self.manager.calls, ["create", "start"])
        self.assertEqual(self.manager.state(), "running")
        self.assertEqual(self.layout.executable.read_bytes(), b"photon 1")
        self.assertEqual(self.layout.executable.name, "photon.exe")
        self.assertEqual(self.layout.config_path.read_text(), 'color = "#8B5CF6"\n')
        self.assertIn("monitor --config", self.manager.spec.binary_path)
        self.assertIn(str(self.layout.executable), self.manager.spec.binary_path)
        self.assertIn(str(self.layout.config_path), self.manager.spec.binary_path)

    def test_the_service_starts_at_boot_before_sign_in(self):  # R19, D16, D18
        self.install()
        spec = self.manager.spec
        self.assertEqual(spec.start_type, "auto")
        self.assertIs(spec.delayed_start, False)
        self.assertEqual(spec.account, "LocalSystem")
        self.assertEqual(spec.dependencies, ("PlugPlay",))
        self.assertNotIn("pawnio", " ".join(spec.dependencies).lower())
        self.assertEqual((spec.restart_attempts, spec.restart_delay_ms), (3, 5000))  # restart on failure

    def test_the_data_directory_is_limited_to_administrators_and_system(self):  # R19, D16
        self.install()
        self.assertTrue(self.layout.data_directory.is_dir())
        (command,) = self.acl_calls
        self.assertEqual(command[:2], ["icacls", str(self.layout.data_directory)])
        self.assertIn("/inheritance:r", command)
        grants = [part for part in command if part.startswith("*S-")]
        self.assertEqual(sorted(grants), sorted([
            "*S-1-5-18:(OI)(CI)F", "*S-1-5-32-544:(OI)(CI)F", "*S-1-5-32-545:(OI)(CI)RX"]))
        # Write or modify rights go to SYSTEM and Administrators only.
        writers = [part for part in grants if part.endswith(":(OI)(CI)F")]
        self.assertEqual(sorted(part.split(":")[0] for part in writers), ["*S-1-5-18", "*S-1-5-32-544"])

    def test_a_second_install_upgrades_and_restarts_the_service(self):  # R8
        self.install()
        self.manager.calls.clear()
        self.source.write_bytes(b"photon 2")
        self.install()
        self.assertEqual(self.manager.calls, ["stop", "update", "start"])
        self.assertEqual(self.layout.executable.read_bytes(), b"photon 2")
        self.assertEqual(self.manager.state(), "running")

    def test_an_existing_configuration_is_kept_on_install(self):  # R13
        self.layout.data_directory.mkdir(parents=True)
        self.layout.config_path.write_text('color = "#00FF00"\n')
        self.install()
        self.assertEqual(self.layout.config_path.read_text(), 'color = "#00FF00"\n')

    def test_installing_from_the_installed_copy_keeps_it(self):  # R8
        self.install()
        self.source = self.layout.executable
        self.install()
        self.assertEqual(self.layout.executable.read_bytes(), b"photon 1")

    def test_install_needs_the_standalone_executable(self):
        with self.assertRaisesRegex(RuntimeError, "standalone executable"):
            self.install(is_bundle=lambda path: False)
        self.assertEqual(self.manager.calls, [])

    def test_uninstall_removes_the_service_and_the_executable_and_keeps_the_configuration(self):  # R10
        self.install()
        self.manager.calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            windows_service.uninstall(manager=self.manager, layout=self.layout, elevated=lambda: True)
        self.assertEqual(self.manager.calls, ["stop", "delete"])
        self.assertIsNone(self.manager.state())
        self.assertFalse(self.layout.install_directory.exists())
        self.assertTrue(self.layout.config_path.is_file())

    def test_uninstall_without_a_service_still_removes_the_executable(self):  # R10
        self.layout.install_directory.mkdir(parents=True)
        self.layout.executable.write_bytes(b"old")
        with contextlib.redirect_stdout(io.StringIO()):
            windows_service.uninstall(manager=self.manager, layout=self.layout, elevated=lambda: True)
        self.assertEqual(self.manager.calls, [])
        self.assertFalse(self.layout.install_directory.exists())

    def test_status_reports_the_state_from_the_service_manager(self):  # R11
        for state, code, text in (("running", 0, "is running"), ("stopped", 3, "is stopped"),
                                  (None, 4, "is not installed")):
            with self.subTest(state=state), contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(windows_service.status(manager=FakeServiceManager(state)), code)
            self.assertIn(text, output.getvalue())

    def test_restart_restarts_through_the_service_manager(self):  # R11
        self.manager = FakeServiceManager("running")
        with contextlib.redirect_stdout(io.StringIO()):
            windows_service.restart(manager=self.manager, elevated=lambda: True)
        self.assertEqual(self.manager.calls, ["stop", "start"])

    def test_restart_of_a_missing_service_asks_for_an_install(self):  # R11
        with self.assertRaisesRegex(RuntimeError, "not installed"):
            windows_service.restart(manager=self.manager, elevated=lambda: True)
        self.assertEqual(self.manager.calls, [])

    def test_install_uninstall_and_restart_without_elevation_change_nothing(self):  # R11
        self.manager = FakeServiceManager("running")
        before = sorted(Path(self.directory.name).rglob("*"))
        for action in ("install", "uninstall", "restart"):
            with self.subTest(action=action):
                with self.assertRaisesRegex(RuntimeError, "elevated prompt"):
                    windows_service.main(action, self.source, manager=self.manager, layout=self.layout,
                                         elevated=lambda: False)
        self.assertEqual(self.manager.calls, [])
        self.assertEqual(self.manager.state(), "running")
        self.assertEqual(self.acl_calls, [])
        self.assertEqual(sorted(Path(self.directory.name).rglob("*")), before)

    def test_status_needs_no_elevation(self):  # R11
        with contextlib.redirect_stdout(io.StringIO()):
            code = windows_service.main("status", self.source, manager=FakeServiceManager("running"),
                                        layout=self.layout, elevated=lambda: False)
        self.assertEqual(code, 0)

    def test_the_service_command_dispatches_to_windows(self):
        with mock.patch.object(service.sys, "platform", "win32"), \
                mock.patch("photon.windows_service.main", return_value=0) as windows_main:
            self.assertEqual(service.main(["status"], executable=self.source), 0)
        windows_main.assert_called_once_with("status", self.source.resolve())


class ServiceCheckTests(unittest.TestCase):
    def check(self, **options):
        defaults = dict(importer=lambda name: None, elevated=lambda: True, library_finder=lambda: None)
        defaults.update(options)
        with mock.patch.object(windows_service, "is_windows", return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()):
            code = windows_service.check_dependencies(**defaults)
        return code, output.getvalue()

    def test_a_missing_pawnio_disables_the_ram_only(self):  # R12, R15
        code, text = self.check()
        self.assertEqual(code, 0)
        self.assertIn("Only the RAM is disabled", text)
        self.assertIn("never installs a driver", text)

    def test_pawnio_present_is_reported(self):  # R12
        with tempfile.TemporaryDirectory() as root:
            module = Path(root) / "SmbusI801.bin"
            module.write_bytes(b"")
            code, text = self.check(library_finder=lambda: Path("C:/Program Files/PawnIO/PawnIOLib.dll"),
                                    module_path=lambda: module)
        self.assertEqual(code, 0)
        self.assertIn("i801 module is available", text)

    def test_a_missing_runtime_is_a_failure(self):  # R12
        def importer(name):
            if name == "win32service":
                raise ImportError("no pywin32")

        code, _text = self.check(importer=importer)
        self.assertEqual(code, 1)

    def test_check_does_not_use_the_service_manager_or_the_disk(self):  # R12
        with mock.patch.object(windows_service, "Win32ServiceManager") as manager, \
                mock.patch.object(windows_service, "secure_data_directory") as secure:
            self.check()
            self.check(elevated=lambda: False)
        manager.assert_not_called()
        secure.assert_not_called()

    def test_not_elevated_is_mentioned_without_failing(self):  # R11, R12
        code, text = self.check(elevated=lambda: False)
        self.assertEqual(code, 0)
        self.assertIn("not elevated", text)


class FakeWin32Service:
    """A fake ``win32service`` module that records what the real one would be asked to do."""

    SC_MANAGER_CONNECT, SC_MANAGER_CREATE_SERVICE = 1, 2
    SERVICE_ALL_ACCESS, SERVICE_QUERY_STATUS, SERVICE_START, SERVICE_STOP, DELETE = 0xF, 4, 0x10, 0x20, 0x40
    SERVICE_WIN32_OWN_PROCESS, SERVICE_AUTO_START, SERVICE_ERROR_NORMAL = 0x10, 2, 1
    SERVICE_CONFIG_DELAYED_AUTO_START_INFO, SERVICE_CONFIG_DESCRIPTION = 3, 1
    SERVICE_CONFIG_FAILURE_ACTIONS, SERVICE_CONFIG_FAILURE_ACTIONS_FLAG = 2, 4
    SC_ACTION_RESTART = 1
    SERVICE_STOPPED, SERVICE_START_PENDING, SERVICE_STOP_PENDING, SERVICE_RUNNING, SERVICE_PAUSED = 1, 2, 3, 4, 7
    SERVICE_CONTROL_STOP = 1

    class Error(Exception):
        def __init__(self, winerror):
            super().__init__(winerror, "fake", "fake error")
            self.winerror = winerror

    def __init__(self, status=None):
        self.calls = []
        self.status = status  # None: no such service; else a list of states, one per query
        self.handles = 0

    def _log(self, name, *args):
        self.calls.append((name, *args))

    def OpenSCManager(self, *args):
        self._log("OpenSCManager", *args)
        return "scm"

    def OpenService(self, scm, name, access):
        self._log("OpenService", name, access)
        if self.status is None:
            raise self.Error(1060)
        return "service"

    def CreateService(self, *args):
        self._log("CreateService", *args)
        return "service"

    def ChangeServiceConfig(self, *args):
        self._log("ChangeServiceConfig", *args)

    def ChangeServiceConfig2(self, handle, level, info):
        self._log("ChangeServiceConfig2", level, info)

    def QueryServiceStatus(self, handle):
        state = self.status.pop(0) if len(self.status) > 1 else self.status[0]
        return (0x10, state)

    def StartService(self, handle, args):
        self._log("StartService")
        self.status = [self.SERVICE_START_PENDING, self.SERVICE_RUNNING]

    def ControlService(self, handle, control):
        self._log("ControlService", control)
        self.status = [self.SERVICE_STOP_PENDING, self.SERVICE_STOPPED]

    def DeleteService(self, handle):
        self._log("DeleteService")

    def CloseServiceHandle(self, handle):
        self._log("CloseServiceHandle", handle)

    def named(self, name):
        return [call[1:] for call in self.calls if call[0] == name]


SPEC = windows_service.service_spec(Layout(Path("C:/Program Files/Photon"), Path("C:/ProgramData/Photon")))


class Win32ServiceManagerTests(unittest.TestCase):
    def manager(self, status=None):
        fake = FakeWin32Service(status)
        return fake, Win32ServiceManager(win32service=fake, sleep=lambda _s: None)

    def test_the_service_is_created_with_automatic_start_as_localsystem_with_plugplay_only(self):  # R19, D16, D18
        fake, manager = self.manager()
        manager.create(SPEC)
        (args,) = fake.named("CreateService")
        scm, name, display, access, kind, start, error, binary, group, tag, dependencies, account, password = args
        self.assertEqual((name, kind, start), ("Photon", fake.SERVICE_WIN32_OWN_PROCESS, fake.SERVICE_AUTO_START))
        self.assertEqual(dependencies, ["PlugPlay"])
        self.assertIsNone(account)  # no account given: LocalSystem
        self.assertIn("monitor --config", binary)

    def test_delayed_start_is_explicitly_off(self):  # R19, D18
        fake, manager = self.manager()
        manager.create(SPEC)
        self.assertIn((fake.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, False), fake.named("ChangeServiceConfig2"))

    def test_the_service_restarts_on_failure(self):  # R8
        fake, manager = self.manager()
        manager.create(SPEC)
        actions = dict(fake.named("ChangeServiceConfig2"))[fake.SERVICE_CONFIG_FAILURE_ACTIONS]
        self.assertEqual(actions["Actions"], [(fake.SC_ACTION_RESTART, 5000)] * 3)
        self.assertIs(dict(fake.named("ChangeServiceConfig2"))[fake.SERVICE_CONFIG_FAILURE_ACTIONS_FLAG], True)

    def test_an_upgrade_reasserts_the_account_dependencies_and_start_type(self):  # R8, R19
        fake, manager = self.manager([FakeWin32Service.SERVICE_STOPPED])
        manager.update(SPEC)
        (args,) = fake.named("ChangeServiceConfig")
        self.assertEqual(args[1:3], (fake.SERVICE_WIN32_OWN_PROCESS, fake.SERVICE_AUTO_START))
        self.assertEqual(args[7:10], (["PlugPlay"], "LocalSystem", ""))
        self.assertIn((fake.SERVICE_CONFIG_DELAYED_AUTO_START_INFO, False), fake.named("ChangeServiceConfig2"))

    def test_a_missing_service_has_no_state(self):  # R11
        fake, manager = self.manager()
        self.assertIsNone(manager.state())
        manager.stop()
        manager.delete()
        self.assertEqual(fake.named("DeleteService"), [])

    def test_state_is_read_with_query_rights_only(self):  # R11
        fake, manager = self.manager([FakeWin32Service.SERVICE_RUNNING])
        self.assertEqual(manager.state(), "running")
        self.assertEqual(fake.named("OpenSCManager"), [(None, None, fake.SC_MANAGER_CONNECT)])
        self.assertEqual(fake.named("OpenService"), [("Photon", fake.SERVICE_QUERY_STATUS)])

    def test_start_and_stop_wait_for_the_service(self):  # R11
        fake, manager = self.manager([FakeWin32Service.SERVICE_STOPPED])
        manager.start()
        self.assertEqual(fake.named("StartService"), [()])
        self.assertEqual(manager.state(), "running")
        manager.stop()
        self.assertEqual(fake.named("ControlService"), [(fake.SERVICE_CONTROL_STOP,)])
        self.assertEqual(manager.state(), "stopped")

    def test_delete_removes_the_service(self):  # R10
        fake, manager = self.manager([FakeWin32Service.SERVICE_STOPPED])
        manager.delete()
        self.assertEqual(fake.named("DeleteService"), [()])

    def test_every_handle_is_closed(self):
        fake, manager = self.manager([FakeWin32Service.SERVICE_STOPPED])
        manager.state()
        manager.start()
        manager.delete()
        opened = len(fake.named("OpenSCManager")) + len(fake.named("OpenService"))
        self.assertEqual(len(fake.named("CloseServiceHandle")), opened)


class FakeMonitor:
    def __init__(self):
        self.resumes, self.stopped, self.started = 0, False, threading.Event()
        self._stop = threading.Event()

    def run(self):
        self.started.set()
        self._stop.wait(5)

    def post_resume(self):
        self.resumes += 1

    def stop(self):
        self.stopped = True
        self._stop.set()


class ServiceHostTests(unittest.TestCase):
    def host(self):
        fake = FakeMonitor()
        return fake, ServiceHost("config.toml", lambda config, stop: fake)

    def run_host(self, host):
        thread = threading.Thread(target=host.run)
        thread.start()
        return thread

    def test_a_resume_power_event_reaches_the_monitor(self):  # R20
        fake, host_ = self.host()
        thread = self.run_host(host_)
        self.assertTrue(fake.started.wait(5))
        host_.power_event(windows_service.PBT_APMRESUMEAUTOMATIC)
        host_.power_event(0x04)  # PBT_APMSUSPEND
        host_.power_event(0x0A)  # PBT_APMPOWERSTATUSCHANGE
        host_.stop()
        thread.join(5)
        self.assertEqual(fake.resumes, 1)
        self.assertTrue(fake.stopped)

    def test_a_resume_before_the_monitor_exists_is_not_lost(self):  # R20
        fake, host_ = self.host()
        host_.power_event(windows_service.PBT_APMRESUMEAUTOMATIC)
        thread = self.run_host(host_)
        self.assertTrue(fake.started.wait(5))
        host_.stop()
        thread.join(5)
        self.assertEqual(fake.resumes, 1)

    def test_a_stop_before_the_monitor_exists_ends_it_at_once(self):
        fake, host_ = self.host()
        host_.stop()
        host_.run()
        self.assertTrue(fake.stopped)


class FakeFramework:
    def __init__(self, args):
        self.args = args
        self.reports = []

    def GetAcceptedControls(self):
        return 0x1

    def ReportServiceStatus(self, state, *args):
        self.reports.append(state)


FAKE_WIN32 = SimpleNamespace(SERVICE_ACCEPT_POWEREVENT=0x40, SERVICE_STOP_PENDING=3, SERVICE_CONTROL_POWEREVENT=0x0D)


class ServiceClassTests(unittest.TestCase):
    def make(self):
        host_ = mock.Mock()
        cls = windows_service.make_service_class(FakeFramework, FAKE_WIN32, lambda: host_)
        return host_, cls, cls(["Photon"])

    def test_the_service_is_named_photon(self):
        _host, cls, _service = self.make()
        self.assertEqual(cls._svc_name_, "Photon")

    def test_power_events_are_accepted_and_a_resume_is_forwarded(self):  # R20
        host_, _cls, svc = self.make()
        self.assertEqual(svc.GetAcceptedControls() & FAKE_WIN32.SERVICE_ACCEPT_POWEREVENT,
                         FAKE_WIN32.SERVICE_ACCEPT_POWEREVENT)
        svc.SvcOtherEx(FAKE_WIN32.SERVICE_CONTROL_POWEREVENT, windows_service.PBT_APMRESUMEAUTOMATIC, None)
        host_.power_event.assert_called_once_with(windows_service.PBT_APMRESUMEAUTOMATIC)

    def test_other_controls_are_not_power_events(self):
        host_, _cls, svc = self.make()
        svc.SvcOtherEx(0x05, 0x12, None)
        host_.power_event.assert_not_called()

    def test_stop_reports_pending_then_stops_the_host(self):
        host_, _cls, svc = self.make()
        svc.SvcStop()
        self.assertEqual(svc.reports, [FAKE_WIN32.SERVICE_STOP_PENDING])
        host_.stop.assert_called_once_with()

    def test_run_blocks_in_the_host_and_logs_its_failure(self):
        host_, _cls, svc = self.make()
        svc.SvcDoRun()
        host_.run.assert_called_once_with()
        host_.run.side_effect = RuntimeError("boom")
        with self.assertLogs("photon.windows_service", level="ERROR"), self.assertRaises(RuntimeError):
            svc.SvcDoRun()


class HostedTests(unittest.TestCase):
    class NotAService(Exception):
        winerror = 1063

    def modules(self, dispatcher):
        manager = mock.Mock()
        manager.StartServiceCtrlDispatcher.side_effect = dispatcher
        return SimpleNamespace(
            servicemanager=manager, win32serviceutil=SimpleNamespace(ServiceFramework=FakeFramework),
            win32service=FAKE_WIN32)

    def test_started_by_the_service_manager_the_service_is_hosted(self):
        modules = self.modules(None)
        foreground = mock.Mock()
        self.assertEqual(windows_service.run_hosted("config.toml", modules=modules, foreground=foreground), 0)
        (service_class,) = modules.servicemanager.PrepareToHostSingle.call_args.args
        self.assertEqual(service_class._svc_name_, "Photon")
        foreground.assert_not_called()

    def test_started_from_a_console_the_monitor_runs_in_the_foreground(self):
        modules = self.modules(self.NotAService())
        foreground = mock.Mock(return_value=0)
        with mock.patch.object(windows_service, "_configure_logging"):
            self.assertEqual(windows_service.run_hosted("config.toml", modules=modules, foreground=foreground), 0)
        foreground.assert_called_once_with("config.toml")

    def test_another_dispatcher_error_is_not_swallowed(self):
        modules = self.modules(RuntimeError("other"))
        with self.assertRaises(RuntimeError):
            windows_service.run_hosted("config.toml", modules=modules, foreground=mock.Mock())


class SafeFolderTests(unittest.TestCase):
    def test_program_files_folders_are_deduplicated_and_skip_unresolved_ones(self):  # R15
        answers = {host.FOLDERID_PROGRAM_FILES: Path("C:/Program Files"),
                   host.FOLDERID_PROGRAM_FILES_X64: Path("C:/Program Files")}
        self.assertEqual(host.program_files_folders(answers.get), [Path("C:/Program Files")])
        self.assertEqual(host.program_files_folders(lambda folder_id: None), [])

    def test_program_data_falls_back_to_the_environment_then_the_default(self):
        with mock.patch.dict(os.environ, {"ProgramData": "D:\\PD"}):
            self.assertEqual(host.program_data_folder(lambda folder_id: None), Path("D:\\PD"))
            self.assertEqual(host.program_data_folder(lambda folder_id: Path("C:/PD")), Path("C:/PD"))
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(host.program_data_folder(lambda folder_id: None), Path(host.WINDOWS_DEFAULT_PROGRAM_DATA))

    def test_a_known_folder_is_unavailable_off_windows(self):
        with mock.patch.object(host, "is_windows", return_value=False):
            self.assertIsNone(host.known_folder(host.FOLDERID_PROGRAM_FILES))


class FakeLibrary:
    def __init__(self, closed, *, open_error=None):
        self.closed, self.open_error = closed, open_error

    def open(self, module):
        if self.open_error:
            raise self.open_error

    def close(self):
        self.closed.append("library")


class FakeHandleMutex:
    def __init__(self, closed):
        self.closed = closed

    def close(self):
        self.closed.append("mutex")


class OpenSmbusLibraryTests(unittest.TestCase):
    """The reviewed hole: handles created outside the try, and library errors escaping."""

    def open(self, *, library_factory, mutex_factory=None, closed=None):
        closed = [] if closed is None else closed
        with tempfile.TemporaryDirectory() as root:
            module = Path(root) / "SmbusI801.bin"
            module.write_bytes(b"module")
            with mock.patch.object(pawnio, "find_library", return_value=Path("PawnIOLib.dll")), \
                    mock.patch.object(pawnio, "is_elevated", return_value=True), \
                    mock.patch.object(pawnio, "module_blob_path", return_value=module), \
                    mock.patch.object(pawnio, "SmbusMutex", mutex_factory or (lambda: FakeHandleMutex(closed))), \
                    mock.patch.object(pawnio, "PawnIoLibrary", library_factory):
                return pawnio.open_smbus_library()

    def test_a_library_that_cannot_load_closes_the_mutex_and_reports_the_ram_unavailable(self):  # R6
        closed = []

        def factory(path):
            raise OSError("not a valid Win32 application")

        with self.assertRaisesRegex(RamUnavailable, "cannot open PawnIO"):
            self.open(library_factory=factory, closed=closed)
        self.assertEqual(closed, ["mutex"])

    def test_a_library_without_the_expected_entry_points_is_reported_unavailable(self):  # R6
        closed = []

        def factory(path):
            raise AttributeError("function 'pawnio_open' not found")

        with self.assertRaisesRegex(RamUnavailable, "pawnio_open"):
            self.open(library_factory=factory, closed=closed)
        self.assertEqual(closed, ["mutex"])

    def test_a_module_that_fails_to_load_closes_both_handles(self):  # R6
        closed = []
        with self.assertRaises(RamUnavailable):
            self.open(library_factory=lambda path: FakeLibrary(closed, open_error=OSError("HRESULT 0x80070005")),
                      closed=closed)
        self.assertEqual(sorted(closed), ["library", "mutex"])

    def test_a_mutex_that_cannot_be_created_is_reported_unavailable(self):  # R6
        def mutex():
            raise RamUnavailable("cannot open the SMBus mutex")

        with self.assertRaisesRegex(RamUnavailable, "SMBus mutex"):
            self.open(library_factory=lambda path: FakeLibrary([]), mutex_factory=mutex)

    def test_a_working_library_is_returned_with_its_mutex(self):
        closed = []
        library, mutex = self.open(library_factory=lambda path: FakeLibrary(closed), closed=closed)
        self.assertIsInstance(mutex, FakeHandleMutex)
        self.assertEqual(closed, [])


RamUnavailable = pawnio.RamUnavailable


if __name__ == "__main__":
    unittest.main()
