"""TDD — an error carries the way out of it.

Baygon already answered a refused permission with the line to add to
baygon.yaml. Everywhere else it answered "retry the step" — advice that
is wrong by construction, since retrying an unset variable fails the
same way.

The adapters almost always know the remedy at the moment they give up:
the variable has a name, the endpoint has an address, the declared
services have a list. That knowledge simply never reached the operator.
Nothing here needs a model to work it out.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.capabilities import ActionableError
from baygon.core.kernel import Kernel
from baygon_plugins._http import EndpointUnreachable
from baygon_plugins.coding_agent import CodingAgent
from baygon_plugins.command_service import CommandService
from baygon_plugins.env_secrets import EnvSecrets
from baygon_plugins.postgres_database import PostgresDatabase

REMEDIATION_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      base:
        type: database
        plugin: baygon_plugins.postgres_database:PostgresDatabase
        default: true
        options:
          dsn_env:
            development: DEMO_ABSENT_DSN
      superviseur:
        type: service
        plugin: baygon_plugins.command_service:CommandService
        default: true
        options:
          services:
            web: "echo ok"
      superviseur_secours:
        type: service
        plugin: baygon_plugins.command_service:CommandService
        options:
          services:
            web: "echo secours"
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      database: true
      restart: true
    """
)


class AdaptersNameTheRemedyTest(unittest.TestCase):
    """Each adapter says what would make the call work."""

    def test_a_missing_dsn_names_the_variable_to_set(self) -> None:
        adapter = PostgresDatabase({"dsn_env": {"production": "PROD_ABSENT_DSN"}})
        with self.assertRaises(ActionableError) as raised:
            adapter.info("production")
        self.assertIn("PROD_ABSENT_DSN", " ".join(raised.exception.options))

    def test_an_undeclared_environment_lists_the_declared_ones(self) -> None:
        adapter = PostgresDatabase({"dsn_env": {"production": "X", "staging": "Y"}})
        with self.assertRaises(ActionableError) as raised:
            adapter.info("development")
        remedy = " ".join(raised.exception.options)
        self.assertIn("production", remedy)
        self.assertIn("staging", remedy)

    def test_a_missing_secret_names_the_variable(self) -> None:
        adapter = EnvSecrets({"prefix": "DEMO_"})
        with self.assertRaises(ActionableError) as raised:
            adapter.get("ABSENT_KEY")
        self.assertIn("DEMO_ABSENT_KEY", " ".join(raised.exception.options))

    def test_an_unknown_service_lists_the_declared_ones(self) -> None:
        adapter = CommandService({"services": {"web": "true", "worker": "true"}})
        with self.assertRaises(ActionableError) as raised:
            adapter.restart(service="api", environment="development")
        remedy = " ".join(raised.exception.options)
        self.assertIn("web", remedy)
        self.assertIn("worker", remedy)

    def test_an_agent_without_a_command_says_what_to_declare(self) -> None:
        with self.assertRaises(ActionableError) as raised:
            CodingAgent({}).fix("corrige le bug")
        self.assertIn("command", " ".join(raised.exception.options))

    def test_an_unreachable_endpoint_offers_a_way_out(self) -> None:
        self.assertTrue(EndpointUnreachable("x", options=["démarre la pile"]).options)


class TheFailureReportCarriesTheRemedyTest(unittest.TestCase):
    """What the operator actually reads, at the end of a failed plan."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(REMEDIATION_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_the_remedy_replaces_the_useless_generic_advice(self) -> None:
        result = self.kernel.run("montre la base de données")
        self.assertFalse(result.success)
        options = result.failure["options"]
        self.assertIn("DEMO_ABSENT_DSN", " ".join(options))
        self.assertNotIn("retry the step", options, "retrying an unset variable fails alike")

    def test_a_missing_capability_says_what_to_declare(self) -> None:
        """No provider at all is the most common wall, and the least explained."""
        result = self.kernel.run("montre-moi les logs")
        self.assertFalse(result.success)
        remedy = " ".join(result.failure["options"])
        self.assertIn("logs", remedy)
        self.assertIn("baygon.yaml", remedy)

    def test_alternatives_are_named_rather_than_alluded_to(self) -> None:
        """"Retry with another implementation" — which one?"""
        options = self.kernel.executor._failure_options(
            self.kernel.plan("redémarre le web").steps[0]
        )
        self.assertTrue(any("superviseur_secours" in o for o in options), options)


if __name__ == "__main__":
    unittest.main()
