"""Checks scripts/get-photon.sh against a fake release.

Stub curl, sudo, id and bundle only log their calls. The PATH holds nothing but the stubs and
a few plain tools, so a real sudo or service install is never reachable.
"""

import hashlib
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "get-photon.sh"
PLAIN_TOOLS = ("sh", "sed", "grep", "head", "cat", "cp", "rm", "mkdir", "mktemp", "sha256sum", "chmod", "printf")

BUNDLE = """#!/bin/sh
echo "bundle $*" >>"$FAKE/log"
case "$*" in
    --version) echo "photon 0.1.0" ;;
    "service check") exit "${FAKE_CHECK:-0}" ;;
esac
"""


@unittest.skipUnless(shutil.which("setsid"), "setsid is needed to run without a terminal")
class GetPhotonTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.stubs = self.root / "stubs"
        self.stubs.mkdir()
        self.cache = self.root / "cache"
        self.log = self.root / "log"
        for folder in ("latest/download", "download/v0.1.0"):
            self._release(folder, BUNDLE)
        self._stub("curl", '# curl -fsSL -o <file> <url>\ncp "$FAKE/release/${4#https://releases.test/}" "$3" 2>/dev/null || exit 22\n')
        self._stub("sudo", 'echo "sudo $*" >>"$FAKE/log"\n"$@"\n')
        self._stub("id", 'echo "${FAKE_UID:-1000}"\n')
        self._stub("uname", 'case $1 in -s) echo Linux ;; -m) echo "${FAKE_ARCH:-x86_64}" ;; esac\n')
        for tool in PLAIN_TOOLS:
            (self.stubs / tool).symlink_to(shutil.which(tool))

    def _stub(self, name, body):
        path = self.stubs / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def _release(self, folder, bundle, listed_bundle=None):
        directory = self.root / "release" / folder
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "photon").write_text(bundle)
        digest = hashlib.sha256((listed_bundle or bundle).encode()).hexdigest()
        (directory / "SHA256SUMS").write_text(f"{digest}  photon\n{'0' * 64}  photon-0.1.0.tar.gz\n")

    def run_script(self, *arguments, **environment):
        self.log.write_text("")
        env = {
            "PATH": str(self.stubs),
            "HOME": str(self.root),
            "XDG_CACHE_HOME": str(self.cache),
            "PHOTON_RELEASES_URL": "https://releases.test",
            "FAKE": str(self.root),
            **environment,
        }
        result = subprocess.run(
            [shutil.which("setsid"), "-w", "sh", str(SCRIPT), *arguments],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
        )
        return result.returncode, result.stdout + result.stderr, self.log.read_text()

    def test_installs_the_checked_bundle(self):
        code, output, log = self.run_script("--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("bundle service check", log)
        self.assertRegex(log, r"sudo \S+/photon-install\.\w+/photon service install")
        self.assertEqual(list(self.cache.iterdir()), [], "the download folder is removed")

    def test_a_named_version_comes_from_its_release(self):
        shutil.rmtree(self.root / "release/latest")
        code, output, log = self.run_script("--yes", "--version", "v0.1.0")
        self.assertEqual(code, 0, output)
        self.assertIn("service install", log)

    def test_a_bad_checksum_installs_nothing(self):
        self._release("latest/download", BUNDLE + "# tampered\n", listed_bundle=BUNDLE)
        code, output, log = self.run_script("--yes")
        self.assertEqual(code, 1)
        self.assertIn("does not match", output)
        self.assertNotIn("service install", log)

    def test_missing_dependencies_install_nothing(self):
        code, output, log = self.run_script("--yes", FAKE_CHECK="1")
        self.assertEqual(code, 1)
        self.assertIn("bundle service check", log)
        self.assertNotIn("service install", log)

    def test_the_installed_version_is_not_reinstalled(self):
        self._stub("photon", 'echo "photon 0.1.0"\n')
        code, output, log = self.run_script("--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("already installed", output)
        self.assertEqual(log, "")

    def test_an_older_version_is_upgraded(self):
        self._stub("photon", 'echo "photon 0.0.9"\n')
        code, output, log = self.run_script("--yes")
        self.assertEqual(code, 0, output)
        self.assertNotIn("already installed", output)
        self.assertIn("service install", log)

    def test_kira_lights_is_announced_as_replaced(self):
        self._stub("kira-lights", "exit 0\n")
        code, output, log = self.run_script("--yes")
        self.assertEqual(code, 0, output)
        self.assertIn("KiraLights is installed", output)
        self.assertIn("service install", log)

    def test_without_a_terminal_it_asks_for_yes(self):
        code, output, log = self.run_script()
        self.assertEqual(code, 1)
        self.assertIn("--yes", output)
        self.assertNotIn("service install", log)

    def test_dry_run_only_prints_the_install(self):
        code, output, log = self.run_script("--yes", "--dry-run")
        self.assertEqual(code, 0, output)
        self.assertIn("would run: sudo", output)
        self.assertNotIn("sudo", log)

    def test_root_is_refused(self):
        code, output, log = self.run_script("--yes", FAKE_UID="0")
        self.assertEqual(code, 1)
        self.assertIn("do not run this script as root", output)
        self.assertEqual(log, "")

    def test_other_architectures_are_refused(self):
        code, output, _log = self.run_script("--yes", FAKE_ARCH="aarch64")
        self.assertEqual(code, 1)
        self.assertIn("x86_64", output)

    def test_help_prints_the_usage(self):
        code, output, _log = self.run_script("--help")
        self.assertEqual(code, 0)
        self.assertIn("--dry-run", output)


if __name__ == "__main__":
    unittest.main()
