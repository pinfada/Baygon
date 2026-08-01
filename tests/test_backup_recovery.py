"""TDD — Backup and Recovery capabilities (chapters 8 and 9).

Backup is a reversible operation; restore is destructive by nature
(it overwrites current state): CRITICAL, always suspended until
explicit validation.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

from baygon.core.errors import ValidationRequiredError
from baygon.core.intent import RiskLevel
from baygon.core.kernel import Kernel

BACKUP_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers:
      vault:
        type: backup
        plugin: tests.helpers:FakeBackup
        default: true
      restorer:
        type: recovery
        plugin: tests.helpers:FakeRecovery
        default: true
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      production: true
    """
)


class BackupRecoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(BACKUP_YAML, encoding="utf-8")
        self.kernel = Kernel.start(tmp.name)

    def test_backup_intent_is_medium_risk(self) -> None:
        plan = self.kernel.plan("sauvegarde la production")
        self.assertEqual(plan.intent.name, "BackupProject")
        self.assertEqual(plan.risk, RiskLevel.MEDIUM)
        self.assertFalse(plan.requires_validation)
        result = self.kernel.execute(plan)
        self.assertTrue(result.success)

    def test_restore_intent_is_critical_and_requires_validation(self) -> None:
        plan = self.kernel.plan("restaure la production")
        self.assertEqual(plan.intent.name, "RestoreProject")
        self.assertEqual(plan.risk, RiskLevel.CRITICAL)
        self.assertTrue(plan.requires_validation)
        with self.assertRaises(ValidationRequiredError):
            self.kernel.execute(plan)
        result = self.kernel.execute(plan, approved=True)
        self.assertTrue(result.success)

    def test_restore_is_critical_even_outside_production(self) -> None:
        # A destructive action stays CRITICAL whatever the environment.
        plan = self.kernel.plan("restore staging")
        self.assertEqual(plan.risk, RiskLevel.CRITICAL)
        self.assertTrue(plan.requires_validation)

    def test_english_backup_wording(self) -> None:
        plan = self.kernel.plan("backup staging")
        self.assertEqual(plan.intent.name, "BackupProject")
        self.assertEqual(plan.steps[0].parameters["environment"], "staging")


if __name__ == "__main__":
    unittest.main()
