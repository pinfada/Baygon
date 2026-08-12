"""TDD — handing a recorded incident to the coding agent.

The pieces were all there and unconnected. An incident leaves a precise
trace in the audit journal: which step, which capability, which cause.
The Dev → QA loop already asks an agent for a fix, checks it with the
project's own test command and gates the result behind explicit
validation. Nothing linked the two: you had to read the failure, then
retype it as a description.

"corrige le dernier incident" closes that gap. The Intent Engine
recognises the phrasing — it parses language; it does not read state —
and the Kernel, which owns the journal, fills in what actually failed.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.errors import BaygonError
from baygon.core.kernel import Kernel

INCIDENT_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      cloud:
        type: deployment
        plugin: tests.helpers:BrokenDeployment
        default: true
      git:
        type: repository
        plugin: tests.helpers:FakeRepository
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
    permissions:
      deploy: true
      production: true
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


class IncidentHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(INCIDENT_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update({"attempts": 0, "fixed_after": 1, "feedbacks": []})

    def _cause_an_incident(self) -> str:
        result = self.kernel.run("deploy to staging")
        self.assertFalse(result.success)
        return result.failure["cause"]

    def test_the_phrasing_is_recognised_as_a_fix(self) -> None:
        self._cause_an_incident()
        plan = self.kernel.plan("corrige le dernier incident")
        self.assertEqual(plan.intent.name, "FixBug")
        self.assertTrue(plan.intent.parameters.get("from_last_incident"))

    def test_the_agent_receives_what_actually_failed(self) -> None:
        cause = self._cause_an_incident()
        plan = self.kernel.plan("corrige le dernier incident")
        description = plan.steps[0].parameters["description"]
        self.assertIn(cause, description)
        self.assertIn("deployment", description, "the capability that failed")
        self.assertIn("DeployProject", description, "the intention being served")

    def test_the_plan_explains_where_the_description_came_from(self) -> None:
        self._cause_an_incident()
        plan = self.kernel.plan("corrige le dernier incident")
        self.assertIn("incident", plan.explain().lower())

    def test_the_qa_gate_and_the_bounded_rounds_still_apply(self) -> None:
        """Handing over an incident changes nothing about the guarantees."""
        self._cause_an_incident()
        plan = self.kernel.plan("corrige le dernier incident")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps],
            [("developer", "fix"), ("workspace", "execute")],
        )
        self.assertEqual(plan.max_rounds, 3)

    def test_the_agent_is_really_asked_and_the_fix_is_checked(self) -> None:
        self._cause_an_incident()
        result = self.kernel.run("corrige le dernier incident")
        self.assertTrue(result.success)
        self.assertEqual(helpers.FIXBUG_STATE["attempts"], 1)
        self.assertIn("provider exploded", helpers.FIXBUG_STATE["descriptions"][-1])

    def test_resume_replays_the_briefed_description_not_the_phrase(self) -> None:
        """Same fidelity rule as for a diagnosis handoff: rebuilding the
        plan from the words would lose the incident the user approved —
        the journal's latest failure is now the fix attempt itself."""
        cause = self._cause_an_incident()
        helpers.FIXBUG_STATE["fixed_after"] = 99  # QA never passes
        result = self.kernel.run("corrige le dernier incident")
        self.assertFalse(result.success)
        helpers.FIXBUG_STATE["fixed_after"] = helpers.FIXBUG_STATE["attempts"] + 1
        resumed = self.kernel.resume()
        self.assertTrue(resumed.success)
        self.assertIn(cause, helpers.FIXBUG_STATE["descriptions"][-1],
                      "the agent must be re-briefed with the original incident")

    def test_without_an_incident_it_says_so_rather_than_inventing_one(self) -> None:
        with self.assertRaises(BaygonError) as raised:
            self.kernel.plan("corrige le dernier incident")
        self.assertIn("no failure", str(raised.exception).lower())

    def test_an_ordinary_fix_request_is_untouched(self) -> None:
        self._cause_an_incident()
        plan = self.kernel.plan("corrige le bug de paiement")
        self.assertFalse(plan.intent.parameters.get("from_last_incident"))
        self.assertIn("paiement", plan.steps[0].parameters["description"])


class IncidentIsOfferedAtTheFailureTest(unittest.TestCase):
    """The offer must appear where the failure is read."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(INCIDENT_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_a_failure_offers_the_coding_agent_when_one_is_declared(self) -> None:
        result = self.kernel.run("deploy to staging")
        offer = " ".join(result.failure["options"])
        self.assertIn("corrige le dernier incident", offer)

    def test_no_agent_declared_means_no_empty_promise(self) -> None:
        without = _without_provider(INCIDENT_YAML, "dev")
        self.assertNotIn("developer", without)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(without, encoding="utf-8")
        result = Kernel.start(tmp.name).run("deploy to staging")
        self.assertNotIn("corrige le dernier incident", " ".join(result.failure["options"]))


if __name__ == "__main__":
    unittest.main()
