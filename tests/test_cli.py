import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from baygon.shell.cli import main
from tests.helpers import MINIMAL_YAML

class CliTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.file = str(Path(tmp.name) / "baygon.yaml")
        yaml = MINIMAL_YAML.replace(
            "providers: {}",
            "providers:\n"
            "      cloud:\n"
            "        type: deployment\n"
            "        plugin: tests.helpers:FakeDeployment\n"
            "        default: true\n"
            "      git:\n"
            "        type: repository\n"
            "        plugin: tests.helpers:FakeRepository\n"
            "        default: true",
        )
        Path(self.file).write_text(yaml, encoding="utf-8")

    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(["-f", self.file, *argv])
        return code, out.getvalue(), err.getvalue()

    def test_validate(self) -> None:
        code, out, _ = self._run("validate")
        self.assertEqual(code, 0)
        self.assertIn("valid", out)

    def test_capabilities(self) -> None:
        code, out, _ = self._run("capabilities")
        self.assertEqual(code, 0)
        self.assertIn("deployment", out)

    def test_plan_explains(self) -> None:
        code, out, _ = self._run("plan", "deploy to staging")
        self.assertEqual(code, 0)
        self.assertIn("DeployProject", out)

    def test_run_production_requires_yes(self) -> None:
        code, _, err = self._run("run", "deploy to production")
        self.assertEqual(code, 3)
        self.assertIn("--yes", err)
        code, out, _ = self._run("run", "deploy to production", "--yes")
        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)

    def test_history_after_run(self) -> None:
        self._run("run", "deploy to staging")
        code, out, _ = self._run("history")
        self.assertEqual(code, 0)
        self.assertIn("DeployProject", out)

    def test_invalid_config_exits_2(self) -> None:
        Path(self.file).write_text("nonsense: true", encoding="utf-8")
        code, _, err = self._run("validate")
        self.assertEqual(code, 2)
        self.assertIn("error", err)

    def test_unknown_intent_exits_2(self) -> None:
        code, _, err = self._run("run", "fais-moi un café")
        self.assertEqual(code, 2)
        self.assertIn("Supported intentions", err)


if __name__ == "__main__":
    unittest.main()
