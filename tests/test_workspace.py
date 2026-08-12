"""TDD — the workspace: one command, a fleet of projects.

Baygon was born repo by repo: one baygon.yaml, one kernel, one journal.
The operator's real question is wider — « est-ce que nous avons des
incidents ? » across everything they run. The workspace adds exactly
two things: the fan-out (ask every project in parallel) and the
synthesis (answer like a briefing, not like a log).

What it must NOT add: shared context. Each project keeps its own
kernel, providers, journal and permissions — isolation is not an
option, it is the construction. And the safety contract stays opt-in:
the autonomous policy is declared in the workspace file by its sole
operator, never assumed.
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.errors import ConfigError
from baygon.core.workspace import Workspace, load_workspace
from baygon.shell.cli import main

#: A project that can answer a diagnosis: logs + metrics + a model.
HEALTHY_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: {name}
    providers:
      logs: {{type: logs, plugin: tests.helpers:FakeLogs, default: true}}
      metrics: {{type: metrics, plugin: tests.helpers:FakeMetrics, default: true}}
      brain: {{type: ai, plugin: tests.helpers:DiagnosingAI, default: true}}
    environments:
      development: {{}}
      staging: {{}}
      production: {{}}
    """
)

#: A project whose deployment explodes — and that can fix itself:
#: coding agent + QA gate, the existing bounded Dev → QA loop.
FRAGILE_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: fragile
    providers:
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:BrokenDeployment
        default: true
      dev:
        type: developer
        plugin: tests.helpers:LoopDevAgent
        default: true
      shell:
        type: workspace
        plugin: tests.helpers:GatedWorkspace
        default: true
    environments:
      development:
      staging:
      production:
    commands:
      test: "npm test"
    permissions:
      deploy: true
    """
)

#: A project with a working deployment, to exercise the approval policy.
DEPLOYABLE_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: {name}
    providers:
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
        default: true
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
    environments:
      development:
      staging:
      production:
    permissions:
      deploy: true
      production: true
    """
)


class WorkspaceCase(unittest.TestCase):
    """Shared scaffolding: temp projects and a workspace file over them."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update(
            {"attempts": 0, "fixed_after": 1, "feedbacks": [], "descriptions": []}
        )
        helpers.SynthesizingAI.prompts.clear()

    def _project(self, name: str, yaml_text: str) -> Path:
        directory = self.root / name
        directory.mkdir()
        (directory / "baygon.yaml").write_text(
            yaml_text.format(name=name) if "{name}" in yaml_text else yaml_text,
            encoding="utf-8",
        )
        return directory

    def _workspace_file(
        self,
        projects: dict[str, Path],
        policy: str = "",
        orchestrator: str = "",
    ) -> Path:
        lines = ["version: 1", "workspace:", "  name: parc", "projects:"]
        for name, path in projects.items():
            lines.append(f"  {name}: {{path: {path.as_posix()}}}")
        if policy:
            lines.append(policy.rstrip())
        if orchestrator:
            lines.append(orchestrator.rstrip())
        file = self.root / "baygon-workspace.yaml"
        file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return file

    AUTONOMOUS = "policy:\n  autonomous: true\n  self_heal: true"
    ORCHESTRATED = "orchestrator:\n  plugin: tests.helpers:SynthesizingAI"


class WorkspaceConfigTest(WorkspaceCase):
    def test_a_workspace_lists_its_projects(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        b = self._project("beta", HEALTHY_YAML)
        config = load_workspace(self._workspace_file({"alpha": a, "beta": b}))
        self.assertEqual(sorted(config.projects), ["alpha", "beta"])

    def test_paths_are_relative_to_the_workspace_file(self) -> None:
        self._project("alpha", HEALTHY_YAML)
        file = self.root / "baygon-workspace.yaml"
        file.write_text(
            "version: 1\nworkspace: {name: parc}\n"
            "projects:\n  alpha: {path: alpha}\n",
            encoding="utf-8",
        )
        workspace = Workspace.start(file)
        self.assertEqual(workspace.projects(), ["alpha"])

    def test_an_unknown_section_is_refused(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        file = self._workspace_file({"alpha": a})
        file.write_text(
            file.read_text(encoding="utf-8") + "surprise: true\n", encoding="utf-8"
        )
        with self.assertRaises(ConfigError):
            load_workspace(file)

    def test_a_workspace_without_projects_is_refused(self) -> None:
        file = self.root / "baygon-workspace.yaml"
        file.write_text("version: 1\nworkspace: {name: parc}\nprojects: {}\n",
                        encoding="utf-8")
        with self.assertRaises(ConfigError):
            load_workspace(file)

    def test_two_names_for_the_same_directory_are_refused(self) -> None:
        """Two aliases of one project would run two kernels on the same
        journal and the same working tree — concurrently. Refused."""
        a = self._project("alpha", HEALTHY_YAML)
        with self.assertRaises(ConfigError):
            load_workspace(self._workspace_file({"alpha": a, "double": a}))

    def test_a_broken_project_is_isolated_not_fatal(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        ghost = self.root / "fantome"
        ghost.mkdir()  # no baygon.yaml inside
        workspace = Workspace.start(self._workspace_file({"alpha": a, "fantome": ghost}))
        self.assertEqual(workspace.projects(), ["alpha"])
        self.assertIn("fantome", workspace.failures)


class WorkspaceFanOutTest(WorkspaceCase):
    def test_the_question_reaches_every_project(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        b = self._project("beta", HEALTHY_YAML)
        workspace = Workspace.start(self._workspace_file({"alpha": a, "beta": b}))
        report = workspace.run("pourquoi le paiement plante ?")
        self.assertEqual(
            {name: outcome.status for name, outcome in report.outcomes.items()},
            {"alpha": "ok", "beta": "ok"},
        )

    def test_each_project_keeps_its_own_journal_and_kernel(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        b = self._project("beta", HEALTHY_YAML)
        workspace = Workspace.start(self._workspace_file({"alpha": a, "beta": b}))
        workspace.run("pourquoi le paiement plante ?")
        self.assertIsNot(workspace.kernel("alpha"), workspace.kernel("beta"))
        for name in ("alpha", "beta"):
            history = workspace.kernel(name).history()
            self.assertEqual(len(history), 1, f"{name} journals its own run only")

    def test_an_unexpected_crash_in_one_project_stays_in_that_project(self) -> None:
        """Isolation must hold for programming errors too, not only for
        well-mannered BaygonErrors: one project's crash is its outcome,
        never the fleet's."""
        a = self._project("alpha", HEALTHY_YAML)
        b = self._project("beta", HEALTHY_YAML)
        workspace = Workspace.start(self._workspace_file({"alpha": a, "beta": b}))

        def explode(*args: object, **kwargs: object) -> None:
            raise RuntimeError("unexpected bug in this kernel")

        workspace.kernel("alpha").plan = explode  # type: ignore[method-assign]
        report = workspace.run("pourquoi le paiement plante ?")
        self.assertEqual(report.outcomes["alpha"].status, "failed")
        self.assertIn("unexpected bug", report.outcomes["alpha"].cause)
        self.assertEqual(report.outcomes["beta"].status, "ok")

    def test_a_project_that_cannot_answer_does_not_sink_the_others(self) -> None:
        """One project has no deployment provider: its refusal is an
        outcome among others, never a workspace-wide crash."""
        a = self._project("alpha", HEALTHY_YAML)
        d = self._project("deployable", DEPLOYABLE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"alpha": a, "deployable": d})
        )
        report = workspace.run("déploie en staging")
        self.assertEqual(report.outcomes["deployable"].status, "ok")
        self.assertEqual(report.outcomes["alpha"].status, "failed")
        self.assertTrue(report.outcomes["alpha"].cause)


class AutonomyPolicyTest(WorkspaceCase):
    def test_without_policy_sensitive_actions_wait_for_validation(self) -> None:
        d = self._project("deployable", DEPLOYABLE_YAML)
        workspace = Workspace.start(self._workspace_file({"deployable": d}))
        report = workspace.run("déploie en production")
        self.assertEqual(report.outcomes["deployable"].status, "needs_validation")
        self.assertEqual(workspace.kernel("deployable").history(), [],
                         "nothing may run before the operator approves")

    def test_the_declared_policy_approves_for_the_solo_operator(self) -> None:
        d = self._project("deployable", DEPLOYABLE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"deployable": d}, policy=self.AUTONOMOUS)
        )
        report = workspace.run("déploie en production")
        self.assertEqual(report.outcomes["deployable"].status, "ok")

    def test_an_explicit_approval_works_without_the_policy(self) -> None:
        d = self._project("deployable", DEPLOYABLE_YAML)
        workspace = Workspace.start(self._workspace_file({"deployable": d}))
        report = workspace.run("déploie en production", approved=True)
        self.assertEqual(report.outcomes["deployable"].status, "ok")


class SelfHealingTest(WorkspaceCase):
    def test_a_failed_run_is_healed_and_the_report_says_so(self) -> None:
        f = self._project("fragile", FRAGILE_YAML)
        a = self._project("atelier", DEPLOYABLE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"fragile": f, "atelier": a}, policy=self.AUTONOMOUS)
        )
        report = workspace.run("déploie en staging")
        self.assertEqual(report.outcomes["fragile"].status, "healed")
        self.assertEqual(report.outcomes["atelier"].status, "ok")
        self.assertEqual(report.global_status, "healed")
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 1,
                         "the existing Dev → QA loop did the healing")

    def test_a_heal_that_fails_asks_for_intervention(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 99  # QA never passes
        f = self._project("fragile", FRAGILE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"fragile": f}, policy=self.AUTONOMOUS)
        )
        report = workspace.run("déploie en staging")
        self.assertEqual(report.outcomes["fragile"].status, "heal_failed")
        self.assertEqual(report.global_status, "attention")
        text = report.render()
        self.assertIn("Intervention requise", text)
        self.assertIn("3", text, "the number of exhausted rounds is named")

    def test_a_second_incident_counts_its_own_rounds_only(self) -> None:
        """Plan ids are content-derived: every healing of the same
        project shares one id in the journal. The report must count the
        rounds of THIS healing, not of every healing ever journaled."""
        f = self._project("fragile", FRAGILE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"fragile": f}, policy=self.AUTONOMOUS)
        )
        first = workspace.run("déploie en staging")
        self.assertEqual(first.outcomes["fragile"].rounds, 1)
        helpers.FIXBUG_STATE["fixed_after"] = helpers.FIXBUG_STATE["attempts"] + 1
        second = workspace.run("déploie en staging")
        self.assertEqual(second.outcomes["fragile"].status, "healed")
        self.assertEqual(second.outcomes["fragile"].rounds, 1,
                         "the first healing's journal rows must not leak in")

    def test_no_healing_without_the_policy(self) -> None:
        """Self-healing fixes code and runs commands: it is opt-in,
        never a default (Article 7)."""
        f = self._project("fragile", FRAGILE_YAML)
        workspace = Workspace.start(self._workspace_file({"fragile": f}))
        report = workspace.run("déploie en staging")
        self.assertEqual(report.outcomes["fragile"].status, "failed")
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 0,
                         "no agent may touch code without the declared policy")


class ExecutiveReportTest(WorkspaceCase):
    def test_the_report_reads_like_a_briefing_not_a_log(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        b = self._project("beta", HEALTHY_YAML)
        workspace = Workspace.start(self._workspace_file({"alpha": a, "beta": b}))
        text = workspace.run("pourquoi le paiement plante ?").render()
        self.assertIn("STATUT GLOBAL", text)
        self.assertIn("opérationnels", text)
        self.assertNotIn("Traceback", text)
        self.assertNotIn('{"', text, "no raw JSON in an executive report")

    def test_healthy_projects_are_grouped_in_one_line(self) -> None:
        f = self._project("fragile", FRAGILE_YAML)
        a = self._project("atelier", DEPLOYABLE_YAML)
        b = self._project("boutique", DEPLOYABLE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"fragile": f, "atelier": a, "boutique": b},
                                 policy=self.AUTONOMOUS)
        )
        text = workspace.run("déploie en staging").render()
        self.assertIn("corrigé automatiquement", text)
        self.assertIn("Aucun incident", text)

    def test_a_healed_incident_names_cause_action_and_reassurance(self) -> None:
        f = self._project("fragile", FRAGILE_YAML)
        workspace = Workspace.start(
            self._workspace_file({"fragile": f}, policy=self.AUTONOMOUS)
        )
        text = workspace.run("déploie en staging").render()
        self.assertIn("provider exploded", text, "the incident's origin")
        self.assertIn("QA", text, "the reassurance: tests went green again")

    def test_the_orchestrator_writes_the_narrative_when_declared(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        workspace = Workspace.start(
            self._workspace_file({"alpha": a}, orchestrator=self.ORCHESTRATED)
        )
        report = workspace.run("pourquoi le paiement plante ?")
        text = workspace.narrate(report)
        self.assertIn("SYNTHÈSE DU MODÈLE", text)
        self.assertIn("alpha", helpers.SynthesizingAI.prompts[-1],
                      "the model synthesizes the gathered facts")

    def test_a_dead_orchestrator_degrades_to_the_deterministic_report(self) -> None:
        """EF-014: the model narrates better, but its absence — or its
        failure — never silences the answer."""
        a = self._project("alpha", HEALTHY_YAML)
        workspace = Workspace.start(
            self._workspace_file(
                {"alpha": a},
                orchestrator="orchestrator:\n  plugin: tests.helpers:ExplodingAI",
            )
        )
        report = workspace.run("pourquoi le paiement plante ?")
        text = workspace.narrate(report)
        self.assertIn("STATUT GLOBAL", text)

    def test_a_broken_orchestrator_never_dirties_the_fleet_status(self) -> None:
        """The narrator is a comfort, not a project: a plugin that fails
        to load must not paint a healthy fleet as needing intervention."""
        a = self._project("alpha", HEALTHY_YAML)
        workspace = Workspace.start(
            self._workspace_file(
                {"alpha": a},
                orchestrator="orchestrator:\n  plugin: nowhere.to.be:Found",
            )
        )
        self.assertTrue(workspace.orchestrator_error)
        report = workspace.run("pourquoi le paiement plante ?")
        self.assertEqual(report.global_status, "ok")
        self.assertNotIn("orchestrator", report.render())
        self.assertIn("STATUT GLOBAL", workspace.narrate(report))


class WorkspaceCliTest(WorkspaceCase):
    def _main(self, *argv: str) -> tuple[int, str]:
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(list(argv))
        return code, stdout.getvalue()

    def test_run_from_the_terminal(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        file = self._workspace_file({"alpha": a})
        code, output = self._main(
            "workspace", "-w", str(file), "run", "pourquoi le paiement plante ?"
        )
        self.assertEqual(code, 0)
        self.assertIn("STATUT GLOBAL", output)

    def test_an_incident_left_open_exits_nonzero(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 99
        f = self._project("fragile", FRAGILE_YAML)
        file = self._workspace_file({"fragile": f}, policy=self.AUTONOMOUS)
        code, output = self._main("workspace", "-w", str(file), "run",
                                  "déploie en staging")
        self.assertEqual(code, 1)
        self.assertIn("Intervention requise", output)

    def test_projects_and_validate_subcommands(self) -> None:
        a = self._project("alpha", HEALTHY_YAML)
        file = self._workspace_file({"alpha": a})
        code, output = self._main("workspace", "-w", str(file), "projects")
        self.assertEqual((code, output.strip()), (0, "alpha"))
        code, output = self._main("workspace", "-w", str(file), "validate")
        self.assertEqual(code, 0)
        self.assertIn("ok", output)


if __name__ == "__main__":
    unittest.main()
