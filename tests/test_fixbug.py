"""TDD — the Dev → QA loop: "Résous le bug de paiement".

The FixBug intent chains: developer.fix (a coding agent, orchestrated
like any specialized tool) → workspace.execute of the declared `test`
command (Baygon's independent QA check) → success notification.
When QA fails, the kernel retries the whole plan with the failure
report injected as feedback to the developer step — bounded rounds,
every attempt audited, final failure notified (chapter 9 error flow).
"""

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.intent import RiskLevel
from baygon.capabilities import ActionableError
from baygon.core.kernel import Kernel

FIXBUG_YAML = textwrap.dedent(
    """
    version: 1
    project: {name: jiyufit}
    providers:
      dev:
        type: developer
        plugin: tests.helpers:LoopDevAgent
        default: true
      shell:
        type: workspace
        plugin: tests.helpers:GatedWorkspace
        default: true
      notifier:
        type: notification
        plugin: tests.helpers:FakeNotification
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    commands:
      test: "npm test"
    """
)


class FixBugIntentTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = FIXBUG_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def setUp(self) -> None:
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update({"attempts": 0, "fixed_after": 1, "feedbacks": []})

    def test_fix_intent_builds_the_dev_qa_notify_chain(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("Résous le bug de paiement")
        self.assertEqual(plan.intent.name, "FixBug")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps],
            [("developer", "fix"), ("workspace", "execute"), ("notification", "notify")],
        )
        self.assertIn("paiement", plan.steps[0].parameters["description"])
        # QA runs the test command declared in baygon.yaml.
        self.assertEqual(plan.steps[1].parameters["command_line"], "npm test")
        self.assertEqual(plan.risk, RiskLevel.MEDIUM)  # code changes are reversible
        self.assertEqual(plan.max_rounds, 3)

    def test_first_attempt_success_notifies_validation(self) -> None:
        kernel = self._kernel()
        result = kernel.run("corrige le bug de paiement")
        self.assertTrue(result.success)
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("validé", notifier.messages[0])

    def test_qa_failure_feeds_back_to_the_developer_and_retries(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 2  # first fix is wrong, second works
        kernel = self._kernel()
        result = kernel.run("Résous le bug de paiement")
        self.assertTrue(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 2)
        feedbacks = helpers.FIXBUG_STATE["feedbacks"]
        self.assertIsNone(feedbacks[0])          # round 1: no feedback yet
        self.assertIn("tests failed", feedbacks[1])  # round 2: QA report injected

    def test_rounds_are_bounded_and_final_failure_is_notified(self) -> None:
        helpers.FIXBUG_STATE["fixed_after"] = 99  # never fixed
        kernel = self._kernel()
        result = kernel.run("répare le bug de paiement")
        self.assertFalse(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 3)  # max_rounds
        notifier = kernel.registry.resolve("notification")
        self.assertEqual(len(notifier.messages), 1)
        self.assertIn("failed", notifier.messages[0])

    def test_without_declared_test_command_the_plan_says_so(self) -> None:
        yaml_without = FIXBUG_YAML.replace('commands:\n  test: "npm test"\n', "")
        kernel = self._kernel(yaml_without)
        plan = kernel.plan("fix the payment bug")
        self.assertEqual([s.capability for s in plan.steps], ["developer"])
        self.assertIn("no declared 'test' command", " ".join(plan.reasoning).lower())


class CodingAgentAdapterTest(unittest.TestCase):
    def test_fix_invokes_the_agent_command_with_the_description(self) -> None:
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, config=None):
                super().__init__(config)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "patched payment handler"

        adapter = FakeAgent({"command": ["claude", "-p", "{prompt}"]})
        result = adapter.fix("Résous le bug de paiement")
        self.assertEqual(adapter.commands[0][:2], ["claude", "-p"])
        self.assertIn("paiement", adapter.commands[0][2])
        self.assertEqual(result["state"], "patched")

    def test_no_vendor_default_the_agent_command_must_be_declared(self) -> None:
        # ENF-019: Baygon favors no AI provider. Without an explicit
        # command the adapter is unavailable and says why.
        from baygon_plugins.coding_agent import CodingAgent

        adapter = CodingAgent({})
        self.assertFalse(adapter.health_check())
        with self.assertRaisesRegex(ActionableError, "coding agent"):
            adapter.fix("corrige le bug")

    def test_any_agent_cli_works_through_the_same_template(self) -> None:
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, config=None):
                super().__init__(config)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "done"

        for template in (
            ["claude", "-p", "{prompt}"],
            ["aider", "--message", "{prompt}", "--yes"],
            ["codex", "exec", "{prompt}"],
            ["gemini", "-p", "{prompt}"],
        ):
            agent = FakeAgent({"command": template})
            agent.fix("répare le paiement")
            self.assertIn("paiement", " ".join(agent.commands[-1]))

    def test_feedback_is_appended_to_the_prompt(self) -> None:
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, config=None):
                super().__init__(config)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "ok"

        adapter = FakeAgent({"command": ["agent", "{prompt}"]})
        adapter.fix("corrige le bug", feedback="2 tests failed: test_refund")
        self.assertIn("test_refund", adapter.commands[0][1])


class AgentBriefingTest(unittest.TestCase):
    """The agent deserves better than a bare prompt.

    A coding agent dropped into a repository knows nothing of its
    conventions. Some read a context file on their own (Claude Code and
    CLAUDE.md); most do not. `briefing_files` levels the field: the
    declared files travel inside the prompt, whoever the agent is —
    provider neutrality (ENF-019) applied to context, not just to the
    command.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)

    def _agent(self, config):
        from baygon_plugins.coding_agent import CodingAgent

        class FakeAgent(CodingAgent):
            def __init__(self, options=None):
                super().__init__(options)
                self.commands = []

            def _run(self, args):
                self.commands.append(args)
                return "done"

        agent = FakeAgent(config)
        agent.project_dir = self.project
        return agent

    def test_declared_briefing_files_travel_inside_the_prompt(self) -> None:
        (self.project / "CLAUDE.md").write_text(
            "Toujours utiliser des requêtes paramétrées.", encoding="utf-8"
        )
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        agent.fix("corrige le bug de paiement")
        prompt = agent.commands[0][1]
        self.assertIn("corrige le bug de paiement", prompt)
        self.assertIn("requêtes paramétrées", prompt)
        self.assertIn("CLAUDE.md", prompt, "the source of the context is named")

    def test_the_task_comes_first_and_the_context_after(self) -> None:
        (self.project / "CLAUDE.md").write_text("contexte projet", encoding="utf-8")
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        agent.fix("corrige le bug")
        prompt = agent.commands[0][1]
        self.assertLess(prompt.index("corrige le bug"), prompt.index("contexte projet"))

    def test_a_missing_declared_file_is_an_error_not_a_shrug(self) -> None:
        from baygon.capabilities import ActionableError

        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        with self.assertRaises(ActionableError) as raised:
            agent.fix("corrige le bug")
        self.assertIn("CLAUDE.md", str(raised.exception))

    def test_an_oversized_file_is_cut_and_says_so(self) -> None:
        """The prompt travels on a command line; it must stay bounded."""
        (self.project / "CLAUDE.md").write_text("x" * 10_000, encoding="utf-8")
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"],
             "briefing_max_chars": 100}
        )
        agent.fix("corrige le bug")
        prompt = agent.commands[0][1]
        self.assertLess(len(prompt), 1_000)
        self.assertIn("truncated", prompt)

    def test_feedback_still_lands_after_the_briefing(self) -> None:
        (self.project / "CLAUDE.md").write_text("contexte", encoding="utf-8")
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        agent.fix("corrige le bug", feedback="2 tests failed: test_refund")
        self.assertIn("test_refund", agent.commands[0][1])

    def test_without_briefing_files_the_prompt_is_unchanged(self) -> None:
        agent = self._agent({"command": ["agent", "{prompt}"]})
        agent.fix("corrige le bug")
        self.assertEqual(agent.commands[0][1], "corrige le bug")

    def test_a_briefing_key_left_empty_means_no_briefing(self) -> None:
        """`briefing_files:` with no value is YAML for None, not a typo
        worth crashing over."""
        agent = self._agent({"command": ["agent", "{prompt}"], "briefing_files": None})
        agent.fix("corrige le bug")
        self.assertEqual(agent.commands[0][1], "corrige le bug")

    def test_a_bare_string_is_refused_with_the_expected_shape(self) -> None:
        """`briefing_files: CLAUDE.md` without brackets must not be
        iterated character by character ("file 'C' not found")."""
        from baygon.capabilities import ActionableError

        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": "CLAUDE.md"}
        )
        with self.assertRaises(ActionableError) as raised:
            agent.fix("corrige le bug")
        self.assertIn("list", str(raised.exception))

    def test_a_file_that_is_not_utf8_is_an_actionable_error(self) -> None:
        """A CLAUDE.md saved in cp1252 — a realistic Windows accident —
        deserves a remedy, not a raw UnicodeDecodeError."""
        from baygon.capabilities import ActionableError

        (self.project / "CLAUDE.md").write_bytes("règles".encode("cp1252"))
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        with self.assertRaises(ActionableError) as raised:
            agent.fix("corrige le bug")
        self.assertIn("UTF-8", str(raised.exception))

    def test_a_windows_bom_does_not_leak_into_the_prompt(self) -> None:
        (self.project / "CLAUDE.md").write_text("contexte", encoding="utf-8-sig")
        agent = self._agent(
            {"command": ["agent", "{prompt}"], "briefing_files": ["CLAUDE.md"]}
        )
        agent.fix("corrige le bug")
        self.assertNotIn("﻿", agent.commands[0][1])


class AgentAvailabilityTest(unittest.TestCase):
    """What counts as a usable program depends on the operating system.

    `shutil.which` answers for POSIX, where the executable bit settles
    the question. On Windows there is no such bit: it accepts only the
    extensions listed in PATHEXT, a rule Python enforces since 3.12. A
    project that ships `./agent.py` next to its baygon.yaml would see
    its agent reported missing while the file sits right there.
    """

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.project = Path(tmp.name)
        self.script = self.project / "agent.py"
        self.script.write_text("print('patched')\n", encoding="utf-8")

    def _agent(self, program: str, by_extension: bool):
        """An agent that judges executability the way one platform does.

        The rule is a seam on the adapter rather than a global patch:
        `os.name` is read by pathlib and shutil too, so forcing it would
        change far more than the question under test.
        """
        from baygon_plugins.coding_agent import CodingAgent

        class PlatformAgent(CodingAgent):
            def _extension_decides_what_is_executable(self) -> bool:
                return by_extension

        agent = PlatformAgent({"command": [program], "cwd": "."})
        agent.project_dir = self.project
        return agent

    def test_windows_trusts_a_program_the_project_ships(self) -> None:
        self.assertTrue(self._agent("./agent.py", by_extension=True).health_check())

    def test_windows_still_refuses_a_program_that_is_not_there(self) -> None:
        """Tolerance is about extensions, never about absence."""
        self.assertFalse(self._agent("./missing.py", by_extension=True).health_check())

    def test_windows_tolerance_does_not_extend_to_the_path_lookup(self) -> None:
        """A program looked up on PATH must actually be found there."""
        agent = self._agent("no-such-agent-anywhere", by_extension=True)
        self.assertFalse(agent.health_check())

    @unittest.skipIf(os.name == "nt", "Windows has no executable bit to require")
    def test_the_executable_bit_still_decides_where_there_is_one(self) -> None:
        """Here the seam is not enough: the assertion is about the real
        `shutil.which`, which judges by PATHEXT on a Windows host
        whatever this adapter thinks."""
        agent = self._agent("./agent.py", by_extension=False)
        self.script.chmod(0o644)
        self.assertFalse(agent.health_check())
        self.script.chmod(0o755)
        self.assertTrue(agent.health_check())

    def test_a_program_that_cannot_be_launched_says_which_and_how(self) -> None:
        """The tolerated case must fail clearly, not with a bare errno.

        No double here: the program really does not exist, so the
        operating system really refuses to launch it.
        """
        agent = self._agent("./not-a-real-program", by_extension=True)
        with self.assertRaises(RuntimeError) as raised:
            agent.fix("corrige le bug")
        message = str(raised.exception)
        self.assertIn("not-a-real-program", message)
        self.assertIn("python", message, "the message must show the portable form")


if __name__ == "__main__":
    unittest.main()
