import tempfile
import unittest
from pathlib import Path
from unittest import mock

from photon import service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.install_directory = root / "usr/local/lib/photon"
        self.command_path = root / "usr/local/bin/photon"
        self.unit_path = root / "etc/systemd/system/photon.service"
        self.config_path = root / "etc/photon/config.toml"
        self.legacy_install_directory = root / "usr/local/lib/kira-lights"
        self.legacy_command_path = root / "usr/local/bin/kira-lights"
        self.legacy_unit_path = root / "etc/systemd/system/kira-lights.service"
        self.legacy_config_path = root / "etc/kira-lights/config.toml"
        patches = (
            mock.patch.object(service, "INSTALL_DIRECTORY", self.install_directory),
            mock.patch.object(service, "INSTALLED_EXECUTABLE", self.install_directory / "photon"),
            mock.patch.object(service, "COMMAND_PATH", self.command_path),
            mock.patch.object(service, "UNIT_PATH", self.unit_path),
            mock.patch.object(service, "CONFIG_PATH", self.config_path),
            mock.patch.object(service, "LEGACY_INSTALL_DIRECTORY", self.legacy_install_directory),
            mock.patch.object(
                service, "LEGACY_INSTALLED_EXECUTABLE", self.legacy_install_directory / "kira-lights"
            ),
            mock.patch.object(service, "LEGACY_COMMAND_PATH", self.legacy_command_path),
            mock.patch.object(service, "LEGACY_UNIT_PATH", self.legacy_unit_path),
            mock.patch.object(service, "LEGACY_CONFIG_PATH", self.legacy_config_path),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_unit_runs_root_monitor_with_the_installed_binary(self):
        contents = service.unit_contents()
        self.assertIn("ExecStart=" + str(self.command_path) + " monitor --config " + str(self.config_path), contents)
        self.assertIn("Restart=on-failure", contents)

    @mock.patch("photon.service.check_dependencies", return_value=0)
    @mock.patch("photon.service._systemctl")
    @mock.patch("photon.service._is_bundle", return_value=True)
    @mock.patch("photon.service.os.geteuid", return_value=0)
    def test_install_copies_bundle_creates_config_and_enables_unit(self, _euid, _bundle, systemctl, _check):
        source = Path(self.directory.name) / "photon"
        source.write_bytes(b"bundle")
        service.install(source)
        self.assertEqual((self.install_directory / "photon").read_bytes(), b"bundle")
        self.assertTrue(self.command_path.is_symlink())
        self.assertEqual(self.command_path.readlink(), self.install_directory / "photon")
        self.assertEqual(self.config_path.read_text(), 'color = "#8B5CF6"\n')
        self.assertIn("ExecStart=", self.unit_path.read_text())
        self.assertEqual(
            systemctl.call_args_list,
            [
                mock.call("daemon-reload"),
                mock.call("enable", "--now", "photon.service"),
                mock.call("restart", "photon.service"),
            ],
        )

    @mock.patch("photon.service.check_dependencies", return_value=0)
    @mock.patch("photon.service._systemctl")
    @mock.patch("photon.service._is_bundle", return_value=True)
    @mock.patch("photon.service.os.geteuid", return_value=0)
    def test_install_replaces_a_kira_lights_installation(self, _euid, _bundle, systemctl, _check):
        self.legacy_install_directory.mkdir(parents=True)
        (self.legacy_install_directory / "kira-lights").write_text("old bundle")
        self.legacy_command_path.parent.mkdir(parents=True)
        self.legacy_command_path.symlink_to(self.legacy_install_directory / "kira-lights")
        self.legacy_unit_path.parent.mkdir(parents=True)
        self.legacy_unit_path.write_text("unit")
        self.legacy_config_path.parent.mkdir(parents=True)
        self.legacy_config_path.write_text('color = "#00ff00"\n')
        source = Path(self.directory.name) / "photon"
        source.write_bytes(b"bundle")
        with mock.patch("builtins.print"):
            service.install(source)
        self.assertEqual(self.config_path.read_text(), 'color = "#00ff00"\n')
        self.assertTrue(self.legacy_config_path.exists())
        self.assertFalse(self.legacy_unit_path.exists())
        self.assertFalse(self.legacy_command_path.is_symlink())
        self.assertFalse(self.legacy_install_directory.exists())
        self.assertEqual(systemctl.call_args_list[0], mock.call("disable", "--now", "kira-lights.service"))
        self.assertIn(mock.call("enable", "--now", "photon.service"), systemctl.call_args_list)

    @mock.patch("photon.service._systemctl")
    def test_migration_keeps_an_existing_photon_config(self, systemctl):
        self.legacy_config_path.parent.mkdir(parents=True)
        self.legacy_config_path.write_text('color = "#00ff00"\n')
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text('color = "#ffffff"\n')
        service._migrate_legacy_install()
        self.assertEqual(self.config_path.read_text(), 'color = "#ffffff"\n')
        systemctl.assert_not_called()

    def test_migration_leaves_an_unmanaged_kira_lights_command(self):
        self.legacy_command_path.parent.mkdir(parents=True)
        self.legacy_command_path.write_text("someone else's command")
        service._migrate_legacy_install()
        self.assertTrue(self.legacy_command_path.exists())

    @mock.patch("photon.service._systemctl")
    @mock.patch("photon.service.os.geteuid", return_value=0)
    def test_uninstall_preserves_config(self, _euid, _systemctl):
        self.install_directory.mkdir(parents=True)
        (self.install_directory / "photon").write_text("bundle")
        self.unit_path.parent.mkdir(parents=True)
        self.unit_path.write_text("unit")
        self.command_path.parent.mkdir(parents=True)
        self.command_path.symlink_to(self.install_directory / "photon")
        self.config_path.parent.mkdir(parents=True)
        self.config_path.write_text('color = "#ffffff"\n')
        service.uninstall()
        self.assertFalse(self.install_directory.exists())
        self.assertFalse(self.unit_path.exists())
        self.assertFalse(self.command_path.exists())
        self.assertTrue(self.config_path.exists())

    def test_install_refuses_to_replace_an_unmanaged_command(self):
        self.command_path.parent.mkdir(parents=True)
        self.command_path.write_text("someone else's command")
        with self.assertRaisesRegex(RuntimeError, "refusing to replace"):
            service._install_command_link()

    @mock.patch("photon.service.os.geteuid", return_value=1000)
    def test_install_requires_root(self, _euid):
        with self.assertRaisesRegex(RuntimeError, "requires root"):
            service.install(Path("/tmp/photon"))

    @mock.patch("photon.service.check_dependencies", return_value=1)
    @mock.patch("photon.service._is_bundle", return_value=True)
    @mock.patch("photon.service.os.geteuid", return_value=0)
    def test_missing_dependencies_do_not_create_installation(self, _euid, _bundle, _check):
        with self.assertRaisesRegex(RuntimeError, "resolve the reported dependencies"):
            service.install(Path("/tmp/photon"))
        self.assertFalse(self.install_directory.exists())
        self.assertFalse(self.unit_path.exists())

    def test_check_reports_missing_python_dependencies(self):
        with mock.patch("builtins.print") as output, mock.patch.object(
            service.importlib, "import_module", side_effect=ImportError("missing")
        ):
            self.assertEqual(service.check_dependencies(), 1)
        self.assertTrue(any("hidraw runtime unavailable" in str(call) for call in output.call_args_list))

    @mock.patch("photon.service._is_bundle", return_value=False)
    @mock.patch("photon.service.os.geteuid", return_value=0)
    def test_install_rejects_a_source_launcher(self, _euid, _bundle):
        with self.assertRaisesRegex(RuntimeError, "PyInstaller bundle"):
            service.install(Path("/tmp/photon"))
