"""TDD — relative paths belong to the project, not to the caller.

A project declares `cwd: .` or `path: app.log` in its own baygon.yaml.
Those paths must mean "next to that file", whatever directory the Shell
happens to run from. Without this, `baygon --projects DIR serve` sends
every project's commands into the server's own working directory —
projects stop being independent (chapter 3).
"""

import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel

SHELL_YAML = textwrap.dedent(
    """
    version: 1
    project: {name: relative}
    providers:
      shell:
        type: workspace
        plugin: baygon_plugins.local_shell:LocalShellWorkspace
        default: true
        options: {cwd: .}
      dev:
        type: developer
        plugin: baygon_plugins.coding_agent:CodingAgent
        default: true
        options: {command: ["./agent.sh"], cwd: .}
    environments: {development: {}, staging: {}, production: {}}
    commands: {test: "cat marker.txt"}
    """
)


class ProjectRelativePathTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name) / "app"
        self.project.mkdir()
        (self.project / "baygon.yaml").write_text(SHELL_YAML, encoding="utf-8")
        (self.project / "marker.txt").write_text("inside the project\n", encoding="utf-8")
        agent = self.project / "agent.sh"
        agent.write_text("#!/bin/sh\necho agent ran in $(pwd)\n", encoding="utf-8")
        agent.chmod(0o755)
        # Run from somewhere else entirely, as a multi-project server does.
        elsewhere = Path(tmp.name) / "elsewhere"
        elsewhere.mkdir()
        previous = os.getcwd()
        os.chdir(elsewhere)
        self.addCleanup(os.chdir, previous)
        self.kernel = Kernel.start(str(self.project))

    def test_declared_command_runs_inside_the_project(self) -> None:
        workspace = self.kernel.registry.resolve("workspace")
        result = workspace.execute(
            command="test", command_line="cat marker.txt", environment="development"
        )
        self.assertIn("inside the project", result["stdout"])

    def test_coding_agent_runs_inside_the_project(self) -> None:
        developer = self.kernel.registry.resolve("developer")
        result = developer.fix(description="peu importe")
        self.assertIn(str(self.project.resolve()), result["output"])

    def test_absolute_paths_are_left_untouched(self) -> None:
        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(other)]))
        (other / "marker.txt").write_text("outside\n", encoding="utf-8")
        workspace = self.kernel.registry.resolve("workspace")
        workspace.config["cwd"] = str(other)
        result = workspace.execute(
            command="test", command_line="cat marker.txt", environment="development"
        )
        self.assertIn("outside", result["stdout"])


class FileLogsPathTest(unittest.TestCase):
    def test_log_files_are_read_next_to_baygon_yaml(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name) / "web"
        project.mkdir()
        (project / "baygon.yaml").write_text(
            textwrap.dedent(
                """
                version: 1
                project: {name: web}
                providers:
                  logs:
                    type: logs
                    plugin: baygon_plugins.file_logs:FileLogs
                    default: true
                    options:
                      files: {production: app.log}
                environments: {development: {}, staging: {}, production: {}}
                """
            ),
            encoding="utf-8",
        )
        (project / "app.log").write_text("ERROR upstream timeout\n", encoding="utf-8")
        previous = os.getcwd()
        os.chdir(tmp.name)
        self.addCleanup(os.chdir, previous)
        kernel = Kernel.start(str(project))
        entries = kernel.registry.resolve("logs").fetch(environment="production")
        self.assertTrue(any("upstream timeout" in str(entry) for entry in entries))


class ProjectLocalPluginTest(unittest.TestCase):
    """A project may ship its own adapter next to its baygon.yaml.

    With several projects managed at once no single PYTHONPATH can cover
    them all, so the project directory itself must be importable while
    its providers load.
    """

    def test_adapter_module_next_to_the_config_is_importable(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        project = Path(tmp.name) / "own"
        project.mkdir()
        (project / "house_notifier.py").write_text(
            textwrap.dedent(
                """
                from typing import Any
                from baygon.capabilities import NotificationCapability


                class HouseNotifier(NotificationCapability):
                    identifier = "house"

                    def notify(self, message: str, **params: Any) -> dict[str, Any]:
                        return {"delivered": True, "message": message}
                """
            ),
            encoding="utf-8",
        )
        (project / "baygon.yaml").write_text(
            textwrap.dedent(
                """
                version: 1
                project: {name: own}
                providers:
                  notifier:
                    type: notification
                    plugin: house_notifier:HouseNotifier
                    default: true
                environments: {development: {}, staging: {}, production: {}}
                """
            ),
            encoding="utf-8",
        )
        kernel = Kernel.start(str(project))
        self.assertEqual(kernel.plugins.failures, {})
        notifier = kernel.registry.resolve("notification")
        self.assertTrue(notifier.notify(message="ok")["delivered"])


if __name__ == "__main__":
    unittest.main()
