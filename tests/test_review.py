"""TDD — the Review capability: publishing the fix (EF-001, Article 9).

Once the Dev -> QA loop is green, the work must reach a human: the
review capability publishes a branch and opens a pull/merge request
through the Git provider. Publishing is outward-facing, so it is a
sensitive action: the plan requires explicit validation.

Baygon never writes the diff itself — it asks the provider to publish
what the coding agent produced.
"""

import tempfile
import textwrap
import unittest
from pathlib import Path

import tests.helpers as helpers
from baygon.core.errors import ValidationRequiredError
from baygon.core.intent import RiskLevel
from baygon.core.kernel import Kernel

REVIEW_YAML = textwrap.dedent(
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
      review:
        type: review
        plugin: tests.helpers:FakeReview
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
    permissions:
      publish: true
    """
)


class ProposeChangesIntentTest(unittest.TestCase):
    def _kernel(self, yaml_content: str = REVIEW_YAML) -> Kernel:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        (Path(tmp.name) / "baygon.yaml").write_text(yaml_content, encoding="utf-8")
        return Kernel.start(tmp.name)

    def setUp(self) -> None:
        helpers.FIXBUG_STATE.clear()
        helpers.FIXBUG_STATE.update({"attempts": 0, "fixed_after": 1, "feedbacks": []})

    def test_propose_intent_resolves_to_the_review_capability(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("propose les changements en revue")
        self.assertEqual(plan.intent.name, "ProposeChanges")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps[:1]],
            [("review", "publish")],
        )

    def test_publishing_is_sensitive_and_requires_validation(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("propose les changements en revue")
        self.assertEqual(plan.risk, RiskLevel.HIGH)
        self.assertTrue(plan.requires_validation)
        with self.assertRaises(ValidationRequiredError):
            kernel.execute(plan)
        result = kernel.execute(plan, approved=True)
        self.assertTrue(result.success)
        self.assertEqual(result.steps[0].output["state"], "published")

    def test_publish_permission_is_required(self) -> None:
        kernel = self._kernel(REVIEW_YAML.replace("  publish: true\n", ""))
        plan = kernel.plan("propose les changements en revue")
        result = kernel.execute(plan, approved=True)
        self.assertFalse(result.success)
        self.assertIn("publish", result.failure["cause"])

    def test_fixbug_chains_into_publication_when_review_is_available(self) -> None:
        kernel = self._kernel()
        plan = kernel.plan("Résous le bug de paiement")
        self.assertEqual(
            [(s.capability, s.action) for s in plan.steps],
            [
                ("developer", "fix"),
                ("workspace", "execute"),
                ("review", "publish"),
                ("notification", "notify"),
            ],
        )
        # Publishing makes the whole plan sensitive: nothing reaches the
        # outside world without an explicit decision (Article 9).
        self.assertTrue(plan.requires_validation)

    def test_fixbug_publishes_the_branch_and_notifies_the_link(self) -> None:
        kernel = self._kernel()
        result = kernel.run("Résous le bug de paiement", approved=True)
        self.assertTrue(result.success)
        review = kernel.registry.resolve("review")
        self.assertEqual(len(review.published), 1)
        published = review.published[0]
        self.assertIn("paiement", published["title"])
        self.assertTrue(published["branch"].startswith("baygon/"))
        notifier = kernel.registry.resolve("notification")
        self.assertIn(published["url"], notifier.messages[0])

    def test_without_review_capability_fixbug_stays_local(self) -> None:
        kernel = self._kernel(
            REVIEW_YAML.replace(
                "  review:\n"
                "    type: review\n"
                "    plugin: tests.helpers:FakeReview\n"
                "    default: true\n",
                "",
            )
        )
        plan = kernel.plan("Résous le bug de paiement")
        self.assertNotIn("review", [s.capability for s in plan.steps])
        self.assertFalse(plan.requires_validation)


class GitHubReviewAdapterTest(unittest.TestCase):
    def test_publish_pushes_the_branch_then_opens_a_pull_request(self) -> None:
        from baygon_plugins.github_review import GitHubReview

        class FakeGitHubReview(GitHubReview):
            def __init__(self, config=None):
                super().__init__(config)
                self.git_calls: list[list[str]] = []
                self.api_calls: list[tuple[str, dict]] = []

            def _git(self, args):
                self.git_calls.append(args)
                if args[0] == "status":
                    return " M paiement.py\n"  # the agent modified the tree
                return ""

            def _post_json(self, path, payload):
                self.api_calls.append((path, payload))
                return {"html_url": "https://github.com/org/app/pull/7", "number": 7}

        adapter = FakeGitHubReview({"repository": "org/app", "base": "main"})
        result = adapter.publish(title="Corrige le bug de paiement", body="QA verte")

        # The branch is created and pushed before the pull request exists.
        verbs = [call[0] for call in adapter.git_calls]
        self.assertLess(verbs.index("checkout"), verbs.index("push"))
        checkout = adapter.git_calls[verbs.index("checkout")]
        self.assertTrue(checkout[-1].startswith("baygon/"))
        self.assertEqual(len(adapter.api_calls), 1)  # API called once, after the push
        path, payload = adapter.api_calls[0]
        self.assertEqual(path, "/repos/org/app/pulls")
        self.assertEqual(payload["base"], "main")
        self.assertEqual(payload["title"], "Corrige le bug de paiement")
        self.assertEqual(result["url"], "https://github.com/org/app/pull/7")
        self.assertEqual(result["state"], "published")

    def test_nothing_to_publish_is_reported_without_calling_the_api(self) -> None:
        from baygon_plugins.github_review import GitHubReview

        class NoChangeReview(GitHubReview):
            def __init__(self, config=None):
                super().__init__(config)
                self.api_calls = []

            def _git(self, args):
                if args[0] == "status":
                    return ""  # clean working tree
                return ""

            def _post_json(self, path, payload):
                self.api_calls.append((path, payload))
                return {}

        adapter = NoChangeReview({"repository": "org/app"})
        result = adapter.publish(title="rien", body="")
        self.assertEqual(result["state"], "nothing-to-publish")
        self.assertEqual(adapter.api_calls, [])


if __name__ == "__main__":
    unittest.main()
