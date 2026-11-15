"""Checks scripts/get-photon.ps1 against a fake release (R1-R10, R22, R23 of the installer).

The functions that download, ask, read the machine and start an elevated process are replaced
by tests/get_photon_driver.ps1, and the release is a temporary folder: no test downloads
anything from the network, raises a UAC prompt or installs the service. The forms that cannot
replace functions (`iex`, the scriptblock form, `-File`) read the fake release through a
file:// PHOTON_RELEASES_URL and never pass -Yes without -DryRun.

The GitHub Windows runner is elevated, where the script refuses to run (R6); the form tests
that need a standard prompt are skipped there and the refusal is checked instead.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "get-photon.ps1"
DRIVER = Path(__file__).resolve().parent / "get_photon_driver.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
POWERSHELL = shutil.which("powershell.exe") or "powershell.exe"
VERSION = "99.0.0"

# A tiny executable that stands for photon.exe: it logs its calls to FAKE_LOG, reports the
# version in version.txt next to it (VERSION when absent) and answers `service check` with
# FAKE_CHECK.
FAKE_EXE_SOURCE = """
using System;
using System.IO;
class Fake {
    static int Main(string[] args) {
        string line = string.Join(" ", args);
        string self = System.Reflection.Assembly.GetExecutingAssembly().Location;
        string log = Environment.GetEnvironmentVariable("FAKE_LOG");
        if (log != null) File.AppendAllText(log, "exe: " + self + " " + line + "\\n");
        if (line == "--version") {
            string file = Path.Combine(Path.GetDirectoryName(self), "version.txt");
            Console.WriteLine("photon " + (File.Exists(file) ? File.ReadAllText(file).Trim() : "%s"));
            return 0;
        }
        if (line == "service check") {
            Console.WriteLine("fake service check");
            return int.Parse(Environment.GetEnvironmentVariable("FAKE_CHECK") ?? "0");
        }
        return 0;
    }
}
""" % VERSION


def powershell(*arguments, environment=None, timeout=120):
    env = {**os.environ, **(environment or {})}
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", *arguments],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace", timeout=timeout,
    )
    return result.returncode, result.stdout + result.stderr


def is_elevated():
    _, output = powershell(
        "-Command",
        "([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent())"
        ".IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)",
    )
    return output.strip() == "True"


@unittest.skipUnless(sys.platform == "win32", "get-photon.ps1 is the Windows installer")
class InstallerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.shared = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.shared.cleanup)
        source = Path(cls.shared.name) / "fake.cs"
        source.write_text(FAKE_EXE_SOURCE)
        cls.fake_exe = Path(cls.shared.name) / "fake.exe"
        code, output = powershell(
            "-Command",
            f"Add-Type -TypeDefinition (Get-Content -Raw '{source}') -OutputAssembly '{cls.fake_exe}' -OutputType ConsoleApplication",
        )
        if code != 0 or not cls.fake_exe.exists():
            raise RuntimeError(f"cannot build the fake photon.exe: {output}")
        cls.fake_hash = hashlib.sha256(cls.fake_exe.read_bytes()).hexdigest()
        cls.elevated = is_elevated()

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.log = self.root / "log"
        self.log.write_text("")
        for folder in ("latest/download", f"download/v{VERSION}"):
            self.release(folder)
        # A fake PawnIO installer (the driver pins its hash) and PawnIO already installed in the
        # fake Program Files folder; the PawnIO tests remove it.
        (self.root / "pawnio").mkdir()
        (self.root / "pawnio" / "PawnIO_setup.exe").write_bytes(b"fake pawnio installer")
        (self.root / "pf" / "PawnIO").mkdir(parents=True)
        (self.root / "pf" / "PawnIO" / "PawnIOLib.dll").write_bytes(b"x")

    def release(self, folder, exe_hash=None, with_exe=True):
        directory = self.root / "release" / folder
        directory.mkdir(parents=True, exist_ok=True)
        if with_exe:
            shutil.copy(self.fake_exe, directory / "photon.exe")
        (directory / "SHA256SUMS").write_text(
            f"{exe_hash or self.fake_hash}  photon.exe\n{'0' * 64}  photon-{VERSION}.tar.gz\n{'1' * 64}  get-photon.ps1\n"
        )

    def install_photon(self, version):
        """A Photon already installed in the fake Program Files folder."""
        directory = self.root / "pf" / "Photon"
        directory.mkdir(parents=True)
        shutil.copy(self.fake_exe, directory / "photon.exe")
        (directory / "version.txt").write_text(version)

    def environment(self, **extra):
        return {
            "FAKE_LOG": str(self.log),
            "LOCALAPPDATA": str(self.root / "local"),
            "PHOTON_RELEASES_URL": "https://releases.test",
            **{key: str(value) for key, value in extra.items()},
        }

    def logged(self):
        return self.log.read_text().splitlines()


class FlowTests(InstallerTestCase):
    """The main flow, with the platform, the download and the elevation replaced."""

    def run_flow(self, *flags, **environment):
        (self.root / "local").mkdir(exist_ok=True)
        (self.root / "pf").mkdir(exist_ok=True)
        _, output = powershell(
            "-File", str(DRIVER), "-Script", str(SCRIPT), "-Root", str(self.root), *flags,
            environment=self.environment(**environment),
        )
        match = re.search(r"^CODE=(\d+)$", output, re.MULTILINE)
        self.assertIsNotNone(match, output)
        return int(match.group(1)), output, self.logged()

    def test_R2_downloads_the_latest_release_and_checks_photon_exe(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        self.assertIn("download: https://releases.test/latest/download/SHA256SUMS", log)
        self.assertIn("download: https://releases.test/latest/download/photon.exe", log)
        self.assertIn("Checksum verified.", output)

    def test_R2_version_names_the_release(self):
        code, output, log = self.run_flow("-Yes", "-Version", f"v{VERSION}")
        self.assertEqual(code, 0, output)
        self.assertIn(f"download: https://releases.test/download/v{VERSION}/SHA256SUMS", log)
        self.assertIn(f"download: https://releases.test/download/v{VERSION}/photon.exe", log)

    def test_R2_mismatch_installs_nothing(self):
        self.release("latest/download", exe_hash="f" * 64)
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 1, output)
        self.assertIn("does not match", output)
        self.assertFalse([line for line in log if line.startswith(("elevated:", "exe:"))], log)

    def test_R2_missing_release_exits_with_one(self):
        shutil.rmtree(self.root / "release" / "latest")
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 1, output)
        self.assertIn("cannot download", output)

    def test_R3_up_to_date_downloads_no_photon_exe_and_installs_nothing(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        self.assertIn(f"Photon {VERSION} is already installed.", output)
        self.assertFalse([line for line in log if line.endswith("photon.exe")], log)
        self.assertFalse([line for line in log if line.startswith(("elevated:", "ask:"))], log)

    def test_R4_up_to_date_checks_with_the_installed_executable(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        installed = str(self.root / "pf" / "Photon" / "photon.exe")
        self.assertIn(f"exe: {installed} service check", log)
        self.assertIn("fake service check", output)

    def test_R4_up_to_date_failed_check_exits_with_one(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow("-Yes", FAKE_CHECK=1)
        self.assertEqual(code, 1, output)
        self.assertNotIn("elevated:", "\n".join(log))

    def test_R4_install_checks_with_the_downloaded_executable_before_asking(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        checks = [line for line in log if line.endswith("service check")]
        self.assertEqual(len(checks), 1, log)
        self.assertNotIn(str(self.root / "pf"), checks[0])
        self.assertIn(str(self.root / "local"), checks[0])

    def test_R4_failed_check_installs_nothing_and_asks_nothing(self):
        code, output, log = self.run_flow("-Yes", FAKE_CHECK=1)
        self.assertEqual(code, 1, output)
        self.assertFalse([line for line in log if line.startswith(("elevated:", "ask:"))], log)

    def test_R5_installs_through_an_elevated_service_install(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        elevated = [line for line in log if line.startswith("elevated:")]
        self.assertEqual(len(elevated), 1, log)
        self.assertTrue(elevated[0].endswith("photon.exe service install"), elevated)
        self.assertIn("service install exited with code 0", output)

    def test_R5_the_question_names_the_version(self):
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertIn(f"ask: Install Photon {VERSION} as a Windows service?", log)

    def test_R5_the_upgrade_question_names_both_versions(self):
        self.install_photon("0.1.0")
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertIn(f"ask: Upgrade Photon 0.1.0 to {VERSION}?", log)

    def test_R5_another_answer_installs_nothing(self):
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="n")
        self.assertEqual(code, 1, output)
        self.assertFalse([line for line in log if line.startswith("elevated:")], log)

    def test_R5_failed_install_points_to_status_and_log(self):
        code, output, log = self.run_flow("-Yes", FAKE_ELEVATION=5)
        self.assertEqual(code, 1, output)
        self.assertIn("exited with code 5", output)
        self.assertIn("service status", output)
        self.assertIn("photon.log", output)

    def test_R5_cancelled_elevation_points_to_status_and_log(self):
        code, output, log = self.run_flow("-Yes", FAKE_ELEVATION="cancel")
        self.assertEqual(code, 1, output)
        self.assertIn("cancelled", output)
        self.assertIn("service status", output)
        self.assertIn("photon.log", output)

    def test_R6_refuses_an_elevated_session(self):
        code, output, log = self.run_flow("-Yes", FAKE_ELEVATED=1)
        self.assertEqual(code, 1, output)
        self.assertIn("standard", output)
        self.assertIn("By hand", output)
        self.assertEqual([line for line in log], [], log)

    def test_R7_yes_answers_the_install_question(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        self.assertFalse([line for line in log if line.startswith("ask:")], log)

    def test_R7_without_yes_and_without_a_console_it_stops_before_installing(self):
        code, output, log = self.run_flow()
        self.assertEqual(code, 1, output)
        self.assertIn("-Yes", output)
        self.assertFalse([line for line in log if line.startswith("elevated:")], log)

    def test_R8_dry_run_changes_nothing_and_prints_the_elevated_command(self):
        code, output, log = self.run_flow("-DryRun")
        self.assertEqual(code, 0, output)
        self.assertIn("would run (elevated):", output)
        self.assertTrue(output.count("photon.exe service install") >= 1)
        self.assertIn("download: https://releases.test/latest/download/photon.exe", log)
        self.assertEqual(len([line for line in log if line.endswith("service check")]), 1, log)
        self.assertFalse([line for line in log if line.startswith(("elevated:", "ask:"))], log)

    def test_R8_dry_run_up_to_date_downloads_no_photon_exe(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow("-DryRun")
        self.assertEqual(code, 0, output)
        self.assertFalse([line for line in log if line.endswith("photon.exe")], log)

    def test_R8_dry_run_still_fails_on_a_mismatch_and_on_a_failed_check(self):
        code, output, _ = self.run_flow("-DryRun", FAKE_CHECK=1)
        self.assertEqual(code, 1, output)
        self.release("latest/download", exe_hash="f" * 64)
        code, output, _ = self.run_flow("-DryRun")
        self.assertEqual(code, 1, output)

    def test_R9_refuses_a_machine_that_is_not_x64(self):
        code, output, log = self.run_flow("-Yes", FAKE_ARCH="Arm64")
        self.assertEqual(code, 1, output)
        self.assertIn("x64", output)
        self.assertEqual(log, [], log)

    def test_R9_refuses_a_machine_that_is_not_windows(self):
        code, output, log = self.run_flow("-Yes", FAKE_WINDOWS=0)
        self.assertEqual(code, 1, output)
        self.assertIn("Windows", output)

    def test_R9_refuses_a_32_bit_powershell_and_names_the_64_bit_one(self):
        code, output, log = self.run_flow("-Yes", FAKE_32BIT=1)
        self.assertEqual(code, 1, output)
        self.assertIn("64-bit", output)
        self.assertEqual(log, [], log)

    def test_R9_help_prints_the_usage_and_exits_with_zero_before_any_refusal(self):
        code, output, log = self.run_flow("-Help", FAKE_ELEVATED=1, FAKE_ARCH="Arm64", FAKE_32BIT=1)
        self.assertEqual(code, 0, output)
        self.assertIn("Usage: get-photon.ps1", output)
        self.assertEqual(log, [], log)

    def test_R10_success_is_zero_and_every_other_outcome_is_one(self):
        outcomes = {
            "installed": (self.run_flow("-Yes")[0], 0),
            "dry run": (self.run_flow("-DryRun")[0], 0),
            "declined": (self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="n")[0], 1),
            "failed install": (self.run_flow("-Yes", FAKE_ELEVATION=1)[0], 1),
            "failed check": (self.run_flow("-Yes", FAKE_CHECK=1)[0], 1),
        }
        for name, (code, expected) in outcomes.items():
            self.assertEqual(code, expected, name)

    def test_R23_the_verified_photon_exe_cannot_be_written_renamed_or_deleted(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        probes = [line for line in log if line.startswith("probe:")]
        self.assertEqual(probes, ["probe: write=blocked rename=blocked delete=blocked read=allowed"], log)

    def test_R22_dot_sourcing_defines_the_functions_and_runs_no_flow(self):
        code, output = powershell(
            "-Command", f". '{SCRIPT}'; if (Get-Command Invoke-PhotonInstall -ErrorAction SilentlyContinue) {{ 'DEFINED' }}; 'AFTER'",
            environment=self.environment(),
        )
        self.assertEqual(code, 0, output)
        self.assertIn("DEFINED", output)
        self.assertIn("AFTER", output)
        self.assertNotIn("Looking for", output)
        self.assertEqual(self.logged(), [])


class PawnIOTests(InstallerTestCase):
    """The PawnIO step (R11-R18, R23): the download, the signature and the elevation are replaced."""

    run_flow = FlowTests.run_flow

    def setUp(self):
        super().setUp()
        shutil.rmtree(self.root / "pf" / "PawnIO", ignore_errors=True)  # PawnIO is missing

    def downloads(self, log):
        return [line for line in log if line.startswith("download:") and "PawnIO" in line]

    def elevated(self, log):
        return [line for line in log if line.startswith("elevated:")]

    def pawnio_asks(self, log):
        return [line for line in log if line.startswith("ask: PawnIO")]

    def test_R11_pawnio_present_makes_no_offer_and_downloads_nothing(self):
        library = self.root / "pf" / "PawnIO"
        library.mkdir(parents=True)
        (library / "PawnIOLib.dll").write_bytes(b"x")
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertNotIn("PawnIO", output)
        self.assertEqual(self.pawnio_asks(log), [], log)
        self.assertEqual(self.downloads(log), [], log)
        self.assertEqual([line for line in self.elevated(log) if "PawnIO" in line], [], log)

    def test_R11_a_dll_outside_the_program_files_folder_does_not_count(self):
        x86 = self.root / "pf (x86)" / "PawnIO"
        x86.mkdir(parents=True)
        (x86 / "PawnIOLib.dll").write_bytes(b"x")
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="n")
        self.assertEqual(len(self.pawnio_asks(log)), 1, log)

    def test_R12_the_question_names_the_version_and_the_url_and_comes_between_check_and_install(self):
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        asks = [line for line in log if line.startswith("ask:")]
        self.assertEqual(len(asks), 2, log)
        self.assertIn("PawnIO 2.2.0", asks[0])
        self.assertIn("https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe", asks[0])
        self.assertIn("kernel driver", asks[0])
        self.assertIn("RAM", asks[0])
        self.assertTrue(asks[1].startswith(f"ask: Install Photon {VERSION}"), asks)
        check = next(index for index, line in enumerate(log) if line.endswith("service check"))
        self.assertLess(check, log.index(asks[0]))
        self.assertLess(log.index(asks[0]), log.index(asks[1]))

    def test_R12_R14_the_pinned_values_are_present_and_consistent(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertRegex(text, r"\$PawnIOVersion = '\d+\.\d+\.\d+'")
        self.assertRegex(text, r"\$PawnIOSha256 = '[0-9a-f]{64}'")
        self.assertRegex(text, r"\$PawnIOSignerSubject = '[^']+'")
        self.assertRegex(text, r"\$PawnIOSignerThumbprint = '[0-9A-F]{40}'")
        version = re.search(r"\$PawnIOVersion = '([^']+)'", text).group(1)
        url = re.search(r"\$PawnIOUrl = '([^']+)'", text).group(1)
        self.assertEqual(url, f"https://github.com/namazso/PawnIO.Setup/releases/download/{version}/PawnIO_setup.exe")

    def test_R13_nothing_is_downloaded_before_a_yes(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="n")
        self.assertEqual(code, 0, output)
        self.assertEqual(self.downloads(log), [], log)
        self.assertEqual(len(self.pawnio_asks(log)), 1, log)

    def test_R13_yes_does_not_answer_the_pawnio_question(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="n")
        self.assertEqual(len(self.pawnio_asks(log)), 1, log)
        self.assertEqual([line for line in self.elevated(log) if "PawnIO" in line], [], log)

    def test_R13_without_a_console_the_offer_is_skipped_and_the_run_goes_on(self):
        code, output, log = self.run_flow("-Yes")
        self.assertEqual(code, 0, output)
        self.assertIn("https://pawnio.eu", output)
        self.assertEqual(self.pawnio_asks(log), [], log)
        self.assertEqual(self.downloads(log), [], log)
        self.assertEqual(len(self.elevated(log)), 1, log)
        self.assertTrue(self.elevated(log)[0].endswith("photon.exe service install"), log)

    def test_R14_R15_a_yes_downloads_verifies_and_runs_the_installer_without_any_option(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(self.downloads(log)), 1, log)
        self.assertIn("signature: PawnIO_setup.exe", log)
        elevated = [line for line in self.elevated(log) if "PawnIO" in line]
        self.assertEqual(len(elevated), 1, log)
        self.assertTrue(elevated[0].endswith("PawnIO_setup.exe "), elevated)  # nothing after the path
        self.assertLess(log.index("signature: PawnIO_setup.exe"), log.index(elevated[0]))

    def assert_verification_failure(self, which, **environment):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y", **environment)
        self.assertEqual(code, 1, output)
        self.assertIn(which, output)
        self.assertEqual(self.elevated(log), [], log)
        self.assertEqual(len(self.pawnio_asks(log)), 1, log)
        self.assertFalse([line for line in log if line.startswith("ask: Install Photon")], log)

    def test_R14_a_wrong_hash_runs_nothing_and_exits_with_one(self):
        self.assert_verification_failure("SHA-256", FAKE_PAWNIO_HASH="wrong")

    def test_R14_a_wrong_signer_subject_runs_nothing_and_exits_with_one(self):
        self.assert_verification_failure("signer subject", FAKE_SIG_SUBJECT="CN=Someone Else")

    def test_R14_a_wrong_signer_thumbprint_runs_nothing_and_exits_with_one(self):
        self.assert_verification_failure("thumbprint", FAKE_SIG_THUMBPRINT="F" * 40)

    def test_R14_an_invalid_signature_runs_nothing_and_exits_with_one(self):
        self.assert_verification_failure("Authenticode signature", FAKE_SIG_STATUS="NotSigned")

    def test_R15_the_installer_is_started_before_the_photon_install(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        elevated = self.elevated(log)
        self.assertEqual(len(elevated), 2, log)
        self.assertIn("PawnIO_setup.exe", elevated[0])
        self.assertTrue(elevated[1].endswith("photon.exe service install"), elevated)

    def test_R16_a_decline_says_the_ram_stays_disabled_and_goes_on(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="n")
        self.assertEqual(code, 0, output)
        self.assertIn("RAM stays disabled", output)
        self.assertIn("service install exited with code 0", output)

    def test_R16_a_failed_installer_says_the_ram_stays_disabled_and_goes_on(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y", FAKE_PAWNIO_ELEVATION=3)
        self.assertEqual(code, 0, output)
        self.assertIn("exited with code 3", output)
        self.assertIn("RAM stays disabled", output)
        self.assertIn("service install exited with code 0", output)

    def test_R16_a_cancelled_installer_says_the_ram_stays_disabled_and_goes_on(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y", FAKE_PAWNIO_ELEVATION="cancel")
        self.assertEqual(code, 0, output)
        self.assertIn("cancelled", output)
        self.assertIn("RAM stays disabled", output)
        self.assertIn("service install exited with code 0", output)

    def test_R17_dry_run_prints_the_version_and_url_and_asks_downloads_and_runs_nothing(self):
        code, output, log = self.run_flow("-DryRun", FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertIn("PawnIO 2.2.0", output)
        self.assertIn("https://github.com/namazso/PawnIO.Setup/releases/download/2.2.0/PawnIO_setup.exe", output)
        self.assertEqual(self.pawnio_asks(log), [], log)
        self.assertEqual(self.downloads(log), [], log)
        self.assertEqual(self.elevated(log), [], log)

    def test_R18_the_offer_is_made_when_photon_is_already_up_to_date(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        self.assertEqual(len(self.pawnio_asks(log)), 1, log)
        elevated = self.elevated(log)
        self.assertEqual(len(elevated), 1, log)
        self.assertIn("PawnIO_setup.exe", elevated[0])
        installed = str(self.root / "pf" / "Photon" / "photon.exe")
        self.assertLess(log.index(f"exe: {installed} service check"), log.index(self.pawnio_asks(log)[0]))

    def test_R18_a_failed_check_makes_no_offer(self):
        self.install_photon(VERSION)
        code, output, log = self.run_flow(FAKE_INTERACTIVE=1, FAKE_ANSWER="y", FAKE_CHECK=1)
        self.assertEqual(code, 1, output)
        self.assertEqual(self.pawnio_asks(log), [], log)

    def test_R23_the_verified_pawnio_installer_cannot_be_written_renamed_or_deleted(self):
        code, output, log = self.run_flow("-Yes", FAKE_INTERACTIVE=1, FAKE_ANSWER="y")
        self.assertEqual(code, 0, output)
        index = next(i for i, line in enumerate(log) if line.startswith("elevated:") and "PawnIO" in line)
        self.assertEqual(log[index + 1], "probe: write=blocked rename=blocked delete=blocked read=allowed", log)


def _elevation_dependent(test):
    """Skips on an elevated runner, where the script refuses to start (R6)."""

    def wrapper(self):
        if self.elevated:
            self.skipTest("the runner is elevated; test_R6_forms_refuse_an_elevated_session covers it")
        test(self)

    wrapper.__name__ = test.__name__
    return wrapper


class FormTests(InstallerTestCase):
    """The documented forms, in a `powershell.exe -NoProfile -Command` session or as a file.

    The functions cannot be replaced here, so the release is read from a file:// URL.
    """

    def environment(self, **extra):
        return {
            **super().environment(**extra),
            "PHOTON_RELEASES_URL": (self.root / "release").as_uri(),
        }

    def session(self, command, **extra):
        (self.root / "local").mkdir(exist_ok=True)
        code, output = powershell(
            "-Command", f"{command}; 'MARKER code=' + $LASTEXITCODE", environment=self.environment(**extra),
        )
        return code, output

    def iex(self, **extra):
        return self.session(f"Get-Content -Raw '{SCRIPT}' | Invoke-Expression", **extra)

    def scriptblock(self, *options, **extra):
        return self.session(f"& ([scriptblock]::Create((Get-Content -Raw '{SCRIPT}'))) {' '.join(options)}", **extra)

    def file(self, *options, **extra):
        (self.root / "local").mkdir(exist_ok=True)
        return powershell("-File", str(SCRIPT), *options, environment=self.environment(**extra))

    def test_R10_R22_help_in_each_form_exits_with_zero(self):
        code, output = self.scriptblock("-Help")
        self.assertIn("Usage: get-photon.ps1", output)
        self.assertIn("MARKER code=0", output)
        code, output = self.file("-Help")
        self.assertEqual(code, 0, output)
        self.assertIn("Usage: get-photon.ps1", output)

    @_elevation_dependent
    def test_R10_R22_dry_run_in_the_scriptblock_form_succeeds_and_the_session_goes_on(self):
        code, output = self.scriptblock("-DryRun")
        self.assertIn("Looking for the latest release", output)
        self.assertIn("would run (elevated):", output)
        self.assertIn("MARKER code=0", output)
        self.assertEqual([line for line in self.logged() if line.startswith("exe:")][0].split()[-2:], ["service", "check"])

    @_elevation_dependent
    def test_R10_R22_failed_check_in_the_scriptblock_form_gives_one(self):
        code, output = self.scriptblock("-DryRun", FAKE_CHECK=1)
        self.assertIn("Looking for the latest release", output)
        self.assertIn("MARKER code=1", output)

    @_elevation_dependent
    def test_R10_R22_iex_form_runs_the_flow_and_reports_one_on_a_failure(self):
        # `iex` passes no option and no console answers the question: the run ends at the
        # failed check, with a code of 1, and the session stays open.
        code, output = self.iex(FAKE_CHECK=1)
        self.assertIn("Looking for the latest release", output)
        self.assertIn("MARKER code=1", output)

    @_elevation_dependent
    def test_R10_R22_iex_form_without_a_console_stops_before_installing(self):
        code, output = self.iex()
        self.assertIn("-Yes", output)
        self.assertIn("MARKER code=1", output)
        self.assertNotIn("service install exited", output)

    @_elevation_dependent
    def test_R10_R22_file_form_exit_code(self):
        code, output = self.file("-DryRun")
        self.assertEqual(code, 0, output)
        self.assertIn("Looking for the latest release", output)
        code, output = self.file("-DryRun", FAKE_CHECK=1)
        self.assertEqual(code, 1, output)

    @_elevation_dependent
    def test_R2_R10_mismatch_gives_one(self):
        self.release("latest/download", exe_hash="f" * 64)
        code, output = self.scriptblock("-DryRun")
        self.assertIn("does not match", output)
        self.assertIn("MARKER code=1", output)

    def test_R6_forms_refuse_an_elevated_session(self):
        if not self.elevated:
            self.skipTest("the runner is not elevated")
        code, output = self.scriptblock("-DryRun")
        self.assertIn("MARKER code=1", output)
        self.assertIn("standard", output)
        code, output = self.iex()
        self.assertIn("MARKER code=1", output)
        code, output = self.file("-DryRun")
        self.assertEqual(code, 1, output)
        self.assertEqual(self.logged(), [])


class ReleaseWorkflowTests(unittest.TestCase):
    def test_R1_release_assets_include_get_photon_ps1_in_sha256sums(self):
        text = WORKFLOW.read_text()
        self.assertIn("cp scripts/get-photon.sh scripts/get-photon.ps1 release/", text)
        match = re.search(r"sha256sum (.*) > SHA256SUMS", text)
        self.assertIsNotNone(match)
        self.assertIn("get-photon.ps1", match.group(1).split())
        self.assertIn("get-photon.sh", match.group(1).split())


if __name__ == "__main__":
    unittest.main()
