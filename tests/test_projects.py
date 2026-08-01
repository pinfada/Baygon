"""TDD — multi-project management (EF-001, Article 14).

Baygon manages several fully independent projects, each described by
its own baygon.yaml. Adding a project requires no core change: the
ProjectManager discovers baygon.yaml files and builds one kernel per
project. A broken project is isolated; the others keep working.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.errors import UnknownProjectError
from baygon.core.projects import ProjectManager


def _project_yaml(name: str) -> str:
    return textwrap.dedent(
        f"""
        version: 1
        project:
          name: {name}
        providers:
          cloud:
            type: deployment
            plugin: tests.helpers:FakeDeployment
            default: true
          git:
            type: repository
            plugin: tests.helpers:FakeRepository
            default: true
        environments:
          development: {{}}
          staging: {{}}
          production: {{}}
        permissions:
          deploy: true
          production: true
        """
    )


class ProjectManagerTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in ("alpha", "beta"):
            directory = self.root / name
            directory.mkdir()
            (directory / "baygon.yaml").write_text(_project_yaml(name), encoding="utf-8")

    def test_discover_finds_every_project(self) -> None:
        manager = ProjectManager.discover(self.root)
        self.assertEqual(manager.projects(), ["alpha", "beta"])

    def test_broken_project_is_isolated(self) -> None:
        broken = self.root / "gamma"
        broken.mkdir()
        (broken / "baygon.yaml").write_text("nonsense: true", encoding="utf-8")
        manager = ProjectManager.discover(self.root)
        self.assertEqual(manager.projects(), ["alpha", "beta"])
        self.assertIn("gamma", manager.failures)

    def test_resolve_by_project_named_in_intent(self) -> None:
        manager = ProjectManager.discover(self.root)
        kernel = manager.resolve("Déploie Alpha en staging")
        self.assertEqual(kernel.config.project_name, "alpha")

    def test_explicit_project_wins_over_text(self) -> None:
        manager = ProjectManager.discover(self.root)
        kernel = manager.resolve("Déploie Alpha en staging", explicit="beta")
        self.assertEqual(kernel.config.project_name, "beta")

    def test_single_project_is_the_default(self) -> None:
        solo_dir = self.root / "beta"
        manager = ProjectManager.discover(solo_dir)
        kernel = manager.resolve("deploy to staging")
        self.assertEqual(kernel.config.project_name, "beta")

    def test_ambiguous_or_unknown_project_raises_with_known_list(self) -> None:
        manager = ProjectManager.discover(self.root)
        with self.assertRaises(UnknownProjectError) as ctx:
            manager.resolve("deploy to staging")
        self.assertEqual(ctx.exception.known, ["alpha", "beta"])
        with self.assertRaises(UnknownProjectError):
            manager.resolve("deploy", explicit="unknown")

    def test_projects_stay_fully_independent(self) -> None:
        manager = ProjectManager.discover(self.root)
        result = manager.resolve("deploy alpha to staging").run("deploy to staging")
        self.assertTrue(result.success)
        self.assertEqual(len(manager.kernel("alpha").history()), 1)
        self.assertEqual(manager.kernel("beta").history(), [])


class ProjectsCliTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name in ("alpha", "beta"):
            directory = self.root / name
            directory.mkdir()
            (directory / "baygon.yaml").write_text(_project_yaml(name), encoding="utf-8")

    def _run(self, *argv: str) -> tuple[int, str, str]:
        import contextlib
        import io

        from baygon.shell.cli import main

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_projects_subcommand_lists_discovered_projects(self) -> None:
        code, out, _ = self._run("--projects", str(self.root), "projects")
        self.assertEqual(code, 0)
        self.assertIn("alpha", out)
        self.assertIn("beta", out)

    def test_run_routes_to_the_project_named_in_the_intent(self) -> None:
        code, out, _ = self._run(
            "--projects", str(self.root), "run", "deploy beta to staging"
        )
        self.assertEqual(code, 0)
        self.assertIn('"success": true', out)

    def test_unknown_project_is_an_error(self) -> None:
        code, _, err = self._run("--projects", str(self.root), "run", "deploy to staging")
        self.assertEqual(code, 2)
        self.assertIn("alpha", err)


if __name__ == "__main__":
    unittest.main()
