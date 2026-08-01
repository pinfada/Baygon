"""TDD — real database capability: PostgreSQL adapter (EF-010).

The adapter returns connection information parsed from a DSN read in
the environment (EF-011: never in configuration, and the password is
never exposed — the console command references the variable, not its
value). The `database` permission (chapter 6) gates the operation.
"""

import os
import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.kernel import Kernel
from baygon_plugins.postgres_database import PostgresDatabase

DB_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      db:
        type: database
        plugin: baygon_plugins.postgres_database:PostgresDatabase
        default: true
        options:
          dsn_env:
            staging: BAYGONTEST_STG_DB
            production: BAYGONTEST_PROD_DB
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      database: true
      production: true
    """
)


class PostgresDatabaseTest(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["BAYGONTEST_STG_DB"] = (
            "postgres://app_user:s3cret-pw@db.staging.example.invalid:5433/appdb"
        )
        self.addCleanup(os.environ.pop, "BAYGONTEST_STG_DB", None)

    def test_info_parses_the_dsn_from_the_environment(self) -> None:
        adapter = PostgresDatabase({"dsn_env": {"staging": "BAYGONTEST_STG_DB"}})
        info = adapter.info("staging")
        self.assertEqual(info["host"], "db.staging.example.invalid")
        self.assertEqual(info["port"], 5433)
        self.assertEqual(info["database"], "appdb")
        self.assertEqual(info["user"], "app_user")

    def test_password_is_never_exposed(self) -> None:
        adapter = PostgresDatabase({"dsn_env": {"staging": "BAYGONTEST_STG_DB"}})
        info = adapter.info("staging")
        self.assertNotIn("s3cret-pw", str(info))
        # The console command references the variable, not the secret.
        self.assertEqual(info["console"], 'psql "$BAYGONTEST_STG_DB"')

    def test_unmapped_environment_raises(self) -> None:
        adapter = PostgresDatabase({"dsn_env": {}})
        with self.assertRaisesRegex(ValueError, "production"):
            adapter.info("production")

    def test_missing_dsn_variable_raises(self) -> None:
        os.environ.pop("BAYGONTEST_ABSENT", None)
        adapter = PostgresDatabase({"dsn_env": {"staging": "BAYGONTEST_ABSENT"}})
        with self.assertRaisesRegex(ValueError, "BAYGONTEST_ABSENT"):
            adapter.info("staging")


class DatabaseIntentTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = DB_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def setUp(self) -> None:
        os.environ["BAYGONTEST_STG_DB"] = (
            "postgres://app_user:s3cret-pw@db.staging.example.invalid:5433/appdb"
        )
        self.addCleanup(os.environ.pop, "BAYGONTEST_STG_DB", None)

    def test_database_intent_resolves_and_executes(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("montre la base de données de staging")
        self.assertEqual(plan.intent.name, "ShowDatabase")
        result = kernel.execute(plan)
        self.assertTrue(result.success)
        self.assertEqual(result.steps[0].output["database"], "appdb")

    def test_database_permission_is_required(self) -> None:
        kernel = self._kernel(DB_YAML.replace("  database: true\n", ""))
        result = kernel.run("montre la base de données de staging")
        self.assertFalse(result.success)
        self.assertIn("database", result.failure["cause"])


if __name__ == "__main__":
    unittest.main()
