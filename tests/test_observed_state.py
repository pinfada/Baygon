"""TDD — never claim a state that was not observed.

`redémarre le web` answered "state: restarted" while Docker was not
even running. No layer had a bug: the command returned zero, because
restarting nothing succeeds. But the answer said the service was back,
and that is what an operator acts on.

An exit code says a command ran. It says nothing about the state of the
system. Baygon does not manage processes and cannot observe them by
itself — so, like everything else here, the observation is *declared*:
a status command per service. Where one exists, the reported state is
what was seen. Where none exists, the answer says the restart was
requested and left unverified, rather than pretending.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

from baygon.capabilities import ServiceCapability
from baygon.core.kernel import Kernel
from baygon_plugins.command_service import CommandService

STATE_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      cloud:
        type: deployment
        plugin: tests.helpers:FakeDeployment
        default: true
      superviseur:
        type: service
        plugin: tests.helpers:ObservableService
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      restart: true
    """
)


class RestartTellsWhatWasObservedTest(unittest.TestCase):
    """The adapter, on its own."""

    def test_without_a_status_command_the_restart_is_not_claimed_as_done(self) -> None:
        adapter = CommandService({"services": {"web": "true"}})
        result = adapter.restart(service="web", environment="development")
        self.assertEqual(result["state"], "restart-requested")
        self.assertFalse(result["verified"])

    def test_with_a_status_command_the_observed_state_is_reported(self) -> None:
        adapter = CommandService({
            "services": {"web": "true"},
            "status": {"web": "echo 'Up 3 seconds'"},
        })
        result = adapter.restart(service="web", environment="development")
        self.assertTrue(result["verified"])
        self.assertIn("Up 3 seconds", result["state"])

    def test_a_restart_that_changed_nothing_is_not_dressed_up_as_success(self) -> None:
        """Exactly the Docker case: the command succeeds, nothing runs."""
        adapter = CommandService({
            "services": {"web": "true"},
            "status": {"web": "true"},   # succeeds, observes nothing
        })
        result = adapter.restart(service="web", environment="development")
        self.assertTrue(result["verified"])
        self.assertEqual(result["state"], "nothing-observed")

    def test_a_status_command_that_fails_leaves_the_state_unknown(self) -> None:
        adapter = CommandService({
            "services": {"web": "true"},
            "status": {"web": "exit 3"},
        })
        result = adapter.restart(service="web", environment="development")
        self.assertFalse(result["verified"])
        self.assertEqual(result["state"], "unknown")
        self.assertIn("exit code 3", result["observation_error"])

    def test_the_state_can_be_asked_without_restarting_anything(self) -> None:
        adapter = CommandService({
            "services": {"web": "true"},
            "status": {"web": "echo 'Up 1 hour'"},
        })
        observed = adapter.status(service="web", environment="development")
        self.assertIn("Up 1 hour", observed["state"])
        self.assertTrue(observed["verified"])

    def test_asking_a_service_with_no_status_command_says_so(self) -> None:
        adapter = CommandService({"services": {"web": "true"}})
        with self.assertRaises(Exception) as raised:
            adapter.status(service="web", environment="development")
        self.assertIn("status", " ".join(getattr(raised.exception, "options", [])))


class AskingForTheStateOfAServiceTest(unittest.TestCase):
    """Through an intention, the way an operator would."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(STATE_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_naming_a_service_asks_the_supervisor_not_the_cloud(self) -> None:
        plan = self.kernel.plan("dans quel état est le worker ?")
        self.assertEqual(plan.intent.name, "ShowStatus")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps], [("service", "status")]
        )
        self.assertEqual(plan.steps[0].parameters["service"], "worker")

    def test_asking_without_naming_a_service_still_asks_the_deployment(self) -> None:
        plan = self.kernel.plan("montre le statut")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps], [("deployment", "status")]
        )

    def test_an_environment_is_not_mistaken_for_a_service(self) -> None:
        plan = self.kernel.plan("quel est l'état de la production ?")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps], [("deployment", "status")]
        )

    def test_reading_a_state_is_read_only(self) -> None:
        plan = self.kernel.plan("dans quel état est le worker ?")
        self.assertEqual(plan.risk.value, "LOW")
        self.assertFalse(plan.requires_validation)

    def test_the_observed_state_comes_back(self) -> None:
        result = self.kernel.run("dans quel état est le worker ?")
        self.assertTrue(result.success)
        self.assertEqual(result.steps[0].output["state"], "Up 2 hours")


class RestartReportsWhatItSawTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(STATE_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_the_plan_says_the_restart_will_be_checked(self) -> None:
        plan = self.kernel.plan("redémarre le worker")
        self.assertIn("état", " ".join(plan.reasoning).lower())

    def test_the_result_carries_the_observation(self) -> None:
        result = self.kernel.run("redémarre le worker")
        self.assertTrue(result.success)
        self.assertTrue(result.steps[0].output["verified"])


class ObservableServiceContractTest(unittest.TestCase):
    def test_status_is_part_of_the_service_contract(self) -> None:
        self.assertTrue(hasattr(ServiceCapability, "status"))

    def test_an_adapter_without_status_cannot_be_registered(self) -> None:
        """The contract is checked at registration, as for every capability."""

        class Incomplete(ServiceCapability):
            identifier = "incomplete"

            def restart(self, service: str, environment: str, **params: Any):
                return {}

        with self.assertRaises(TypeError):
            Incomplete({})


if __name__ == "__main__":
    unittest.main()
