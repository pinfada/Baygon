"""TDD — handing a recorded diagnosis to the coding agent.

"corrige le dernier incident" already reconnects an execution *failure*
to the Dev → QA loop. But the more common path is the other one: a
Diagnose run **succeeds**, the model reads the logs and names a probable
bug — and nothing lets the operator say "then fix that". The analysis
had to be read on one screen and retyped on another.

"corrige le dernier diagnostic" closes that gap the same way: the
Intent Engine recognises the phrasing — it parses language, never
state — and the Kernel, which owns the journal, hands the agent what
the diagnosis actually found. A diagnosis made without AI still hands
over its raw evidence: degraded, never broken (EF-014).
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.errors import BaygonError
from baygon.core.kernel import Kernel

DIAGNOSIS_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      logs:
        type: logs
        plugin: tests.helpers:FakeLogs
        default: true
      metrics:
        type: metrics
        plugin: tests.helpers:FakeMetrics
        default: true
      brain:
        type: ai
        plugin: tests.helpers:DiagnosingAI
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
      development: {}
      staging: {}
      production: {}
    commands:
      test: "npm test"
    """
)


def _without_provider(yaml_text: str, name: str) -> str:
    """Same configuration minus one provider block."""
    lines = yaml_text.splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.strip() == f"{name}:")
    end = next(
        i for i in range(start + 1, len(lines))
        if lines[i].strip() and not lines[i].startswith("    ")
    )
    return "".join(lines[:start] + lines[end:])


class DiagnosisHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.kernel = self._kernel(DIAGNOSIS_YAML)
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update(
            {"attempts": 0, "fixed_after": 1, "feedbacks": [], "descriptions": []}
        )

    def _kernel(self, yaml_content: str) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def _diagnose(self, kernel: Kernel | None = None) -> None:
        result = (kernel or self.kernel).run("pourquoi le paiement plante ?")
        self.assertTrue(result.success)

    def test_the_phrasing_is_recognised_as_a_fix(self) -> None:
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        self.assertEqual(plan.intent.name, "FixBug")
        self.assertTrue(plan.intent.parameters.get("from_last_diagnosis"))

    def test_the_agent_receives_what_the_diagnosis_found(self) -> None:
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        description = plan.steps[0].parameters["description"]
        self.assertIn("payment.py ligne 42", description, "the model's analysis")
        self.assertIn("pourquoi le paiement plante ?", description,
                      "the question the diagnosis answered")

    def test_the_plan_explains_where_the_description_came_from(self) -> None:
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        self.assertIn("diagnostic", plan.explain().lower())

    def test_the_qa_gate_and_the_bounded_rounds_still_apply(self) -> None:
        """Handing over a diagnosis changes nothing about the guarantees."""
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps],
            [("developer", "fix"), ("workspace", "execute")],
        )
        self.assertEqual(plan.max_rounds, 3)

    def test_the_agent_is_really_asked_and_the_fix_is_checked(self) -> None:
        self._diagnose()
        result = self.kernel.run("corrige le dernier diagnostic")
        self.assertTrue(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 1)
        self.assertIn("payment.py ligne 42",
                      helpers.FIXBUG_STATE["descriptions"][-1])

    def test_without_a_diagnosis_it_says_so_rather_than_inventing_one(self) -> None:
        with self.assertRaises(BaygonError) as raised:
            self.kernel.plan("corrige le dernier diagnostic")
        self.assertIn("no diagnosis", str(raised.exception).lower())

    def test_a_diagnosis_made_without_ai_hands_over_its_evidence(self) -> None:
        """Degraded diagnosis, degraded handoff — never a broken one."""
        kernel = self._kernel(_without_provider(DIAGNOSIS_YAML, "brain"))
        self._diagnose(kernel)
        plan = kernel.plan("corrige le dernier diagnostic")
        description = plan.steps[0].parameters["description"]
        self.assertIn("log line", description, "the gathered evidence")

    def test_an_empty_ai_answer_counts_as_no_analysis_at_all(self) -> None:
        """A model can succeed and still say nothing (a tool-use-only
        response). An empty analysis must not shadow the real evidence
        that was gathered — nor claim to be the model's word."""
        self.addCleanup(
            setattr, helpers.DiagnosingAI, "analysis", helpers.DiagnosingAI.analysis
        )
        helpers.DiagnosingAI.analysis = ""
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        description = plan.steps[0].parameters["description"]
        self.assertIn("log line", description, "the evidence fallback applies")
        self.assertNotIn("établi par le modèle", description)

    def test_the_latest_diagnosis_wins(self) -> None:
        self._diagnose()
        self.addCleanup(
            setattr, helpers.DiagnosingAI, "analysis", helpers.DiagnosingAI.analysis
        )
        helpers.DiagnosingAI.analysis = "Cette fois c'est le cache Redis qui sature."
        self._diagnose()
        plan = self.kernel.plan("corrige le dernier diagnostic")
        self.assertIn("Redis", plan.steps[0].parameters["description"])

    def test_resume_replays_the_briefed_description_not_the_phrase(self) -> None:
        """The description the user approved must survive a resume.

        Rebuilding the plan from the words alone would hand the agent
        "corrige le dernier diagnostic" — or worse, a description drawn
        from a journal that has moved on since the approval.
        """
        self._diagnose()
        helpers.FIXBUG_STATE["fixed_after"] = 99  # QA never passes
        result = self.kernel.run("corrige le dernier diagnostic")
        self.assertFalse(result.success)
        helpers.FIXBUG_STATE["fixed_after"] = helpers.FIXBUG_STATE["attempts"] + 1
        resumed = self.kernel.resume()
        self.assertTrue(resumed.success)
        self.assertIn("payment.py ligne 42",
                      helpers.FIXBUG_STATE["descriptions"][-1],
                      "the agent must be re-briefed with the diagnosis")

    def test_an_ordinary_fix_request_is_untouched(self) -> None:
        self._diagnose()
        plan = self.kernel.plan("corrige le bug de paiement")
        self.assertFalse(plan.intent.parameters.get("from_last_diagnosis"))
        self.assertIn("paiement", plan.steps[0].parameters["description"])


if __name__ == "__main__":
    unittest.main()
