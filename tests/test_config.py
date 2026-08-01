import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.config import load_config
from baygon.core.errors import ConfigError
from tests.helpers import MINIMAL_YAML, write_config


class ConfigLoaderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def test_valid_minimal_config(self) -> None:
        file = write_config(self.dir)
        config = load_config(file)
        self.assertEqual(config.project_name, "demo")
        self.assertEqual(config.version, 1)
        self.assertIn("production", config.environments)

    def test_directory_path_resolves_to_baygon_yaml(self) -> None:
        write_config(self.dir)
        config = load_config(self.dir)
        self.assertEqual(config.project_name, "demo")

    def test_missing_file_forbids_execution(self) -> None:
        with self.assertRaises(ConfigError):
            load_config(self.dir / "absent.yaml")

    def test_invalid_yaml_forbids_execution(self) -> None:
        file = self.dir / "baygon.yaml"
        file.write_text("version: [unclosed", encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_config(file)

    def test_missing_required_environment(self) -> None:
        content = MINIMAL_YAML.replace("  production: {}\n", "")
        file = write_config(self.dir, content)
        with self.assertRaisesRegex(ConfigError, "production"):
            load_config(file)

    def test_unknown_section_rejected(self) -> None:
        file = write_config(self.dir, MINIMAL_YAML + "\nmystery: true\n")
        with self.assertRaisesRegex(ConfigError, "mystery"):
            load_config(file)

    def test_unsupported_version_rejected(self) -> None:
        file = write_config(self.dir, MINIMAL_YAML.replace("version: 1", "version: 99"))
        with self.assertRaisesRegex(ConfigError, "version"):
            load_config(file)

    def test_provider_requires_type_and_plugin(self) -> None:
        content = textwrap.dedent(
            """
            version: 1
            project: {name: demo}
            providers:
              git: {type: repository}
            environments:
              development: {}
              staging: {}
              production: {}
            """
        )
        file = write_config(self.dir, content)
        with self.assertRaisesRegex(ConfigError, "plugin"):
            load_config(file)

    def test_undeclared_permission_is_denied(self) -> None:
        file = write_config(self.dir)
        config = load_config(file)
        self.assertTrue(config.is_allowed("deploy"))
        self.assertFalse(config.is_allowed("ssh"))


if __name__ == "__main__":
    unittest.main()
