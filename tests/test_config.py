import tempfile
import unittest
from pathlib import Path

from photon.config import ConfigError, format_color, load_config, resolve_color


class ConfigTests(unittest.TestCase):
    def write_config(self, contents: str) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.toml"
        path.write_text(contents, encoding="utf-8")
        return path

    def test_loads_one_global_color(self):
        config = load_config(self.write_config('color = "#8B5CF6"\n'))
        self.assertEqual(config.color, (0x8B, 0x5C, 0xF6))

    def test_missing_config_uses_default_color(self):
        config = load_config("/tmp/photon-config-does-not-exist.toml")
        self.assertEqual(config.color, (0x8B, 0x5C, 0xF6))

    def test_rejects_malformed_color(self):
        with self.assertRaisesRegex(ConfigError, "exactly #RRGGBB"):
            load_config(self.write_config('color = "red"\n'))

    def test_rejects_unknown_keys(self):
        with self.assertRaisesRegex(ConfigError, "unknown configuration key"):
            load_config(self.write_config('color = "#ff0000"\ndevice = "g733"\n'))

    def test_rejects_missing_color(self):
        with self.assertRaisesRegex(ConfigError, "requires a color key"):
            load_config(self.write_config("# no color\n"))

    def test_cli_color_overrides_config(self):
        config = self.write_config('color = "#000000"\n')
        self.assertEqual(resolve_color("#ff0000", config), (0xFF, 0, 0))

    def test_formats_resolved_color_for_output(self):
        self.assertEqual(format_color((0x8B, 0x5C, 0xF6)), "#8B5CF6")


if __name__ == "__main__":
    unittest.main()
