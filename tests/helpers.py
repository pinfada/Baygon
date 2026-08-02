"""Shared test fixtures: in-memory fake implementations and configs."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from baygon.capabilities import (
    AICapability,
    BackupCapability,
    DeveloperCapability,
    DeploymentCapability,
    LogsCapability,
    MetricsCapability,
    NotificationCapability,
    RecoveryCapability,
    RepositoryCapability,
    ReviewCapability,
    WorkspaceCapability,
)

MINIMAL_YAML = textwrap.dedent(
    """
    version: 1
    project:
      name: demo
    providers: {}
    environments:
      development: {}
      staging: {}
      production: {}
    permissions:
      deploy: true
      production: true
    """
)


def write_config(directory: Path, content: str = MINIMAL_YAML) -> Path:
    file = directory / "baygon.yaml"
    file.write_text(content, encoding="utf-8")
    return file


class FakeRepository(RepositoryCapability):
    identifier = "fake-repo"

    def get_latest_commit(self, **params: Any) -> dict[str, Any]:
        return {"sha": "abc123", "author": "test", "subject": "initial"}

    def history(self, limit: int = 10, **params: Any) -> list[dict[str, Any]]:
        return [{"sha": "abc123", "author": "test", "subject": "initial"}]

    def diff(self, **params: Any) -> str:
        return ""


class FakeDeployment(DeploymentCapability):
    identifier = "fake-deploy"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        self.calls.append(("deploy", {"environment": environment, **params}))
        return {"environment": environment, "state": "live"}

    def status(self, environment: str, **params: Any) -> dict[str, Any]:
        return {"environment": environment, "state": "live"}

    def rollback(self, environment: str, **params: Any) -> dict[str, Any]:
        return {"environment": environment, "state": "rolled-back"}


class BrokenDeployment(FakeDeployment):
    identifier = "broken-deploy"

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        raise RuntimeError("provider exploded")


class FakeLogs(LogsCapability):
    identifier = "fake-logs"

    def fetch(self, environment: str, since_hours: int = 1, **params: Any) -> list[str]:
        return [f"{environment} log line"]


class FakeMetrics(MetricsCapability):
    identifier = "fake-metrics"

    def fetch(self, environment: str, **params: Any) -> dict[str, Any]:
        return {"latency_ms": 10}


class CountingRepository(FakeRepository):
    """Counts calls so tests can prove a step was not re-executed."""

    identifier = "counting-repo"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.calls = 0

    def get_latest_commit(self, **params: Any) -> dict[str, Any]:
        self.calls += 1
        return super().get_latest_commit(**params)


#: Shared switch for FlakyDeployment instances created via plugin loading.
FLAKY_FAIL_ONCE: list[bool] = []


class FlakyDeployment(FakeDeployment):
    """Fails on demand, then succeeds — simulates a transient outage."""

    identifier = "flaky-deploy"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.fail_next = False

    def deploy(self, environment: str, **params: Any) -> dict[str, Any]:
        if self.fail_next or (FLAKY_FAIL_ONCE and FLAKY_FAIL_ONCE.pop()):
            self.fail_next = False
            raise RuntimeError("transient provider outage")
        return super().deploy(environment, **params)


class FakeWorkspace(WorkspaceCapability):
    identifier = "fake-workspace"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.executed: list[tuple[str, str, str]] = []

    def execute(self, command: str, command_line: str, environment: str, **params: Any) -> dict[str, Any]:
        self.executed.append((command, command_line, environment))
        return {"command": command, "exit_code": 0}


class FakeBackup(BackupCapability):
    identifier = "fake-backup"

    def backup(self, environment: str, **params: Any) -> dict[str, Any]:
        return {"environment": environment, "state": "backed-up"}


class FakeRecovery(RecoveryCapability):
    identifier = "fake-recovery"

    def restore(self, environment: str, **params: Any) -> dict[str, Any]:
        return {"environment": environment, "state": "restored"}


#: Shared state for the FixBug loop tests (reset in each test's setUp).
FIXBUG_STATE: dict[str, Any] = {"attempts": 0, "fixed_after": 1, "feedbacks": []}


class LoopDevAgent(DeveloperCapability):
    """Coding agent whose fixes only work from attempt `fixed_after` on."""

    identifier = "loop-dev"

    def fix(self, description: str, feedback: str | None = None, **params: Any) -> dict[str, Any]:
        FIXBUG_STATE["attempts"] += 1
        FIXBUG_STATE["feedbacks"].append(feedback)
        return {"state": "patched", "attempt": FIXBUG_STATE["attempts"]}


class GatedWorkspace(WorkspaceCapability):
    """QA gate: the test command passes only once the fix is good."""

    identifier = "gated-workspace"

    def execute(self, command: str, command_line: str, environment: str, **params: Any) -> dict[str, Any]:
        if FIXBUG_STATE["attempts"] < FIXBUG_STATE["fixed_after"]:
            raise RuntimeError("2 tests failed: test_refund, test_checkout")
        return {"command": command, "exit_code": 0}


class ClassifierAI(AICapability):
    """AI double for intent-classification tests: scripted answer."""

    identifier = "classifier-ai"
    #: Class-level so the plugin loader's instance shares it with tests.
    answer = "Diagnose"
    prompts: list[str] = []

    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str:
        ClassifierAI.prompts.append(prompt)
        return ClassifierAI.answer


class FakeReview(ReviewCapability):
    identifier = "fake-review"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.published: list[dict[str, Any]] = []

    def publish(self, title: str, body: str = "", **params: Any) -> dict[str, Any]:
        entry = {
            "title": title,
            "body": body,
            "branch": f"baygon/fix-{len(self.published) + 1}",
            "url": f"https://git.example/pull/{len(self.published) + 1}",
            "state": "published",
        }
        self.published.append(entry)
        return entry


class FakeNotification(NotificationCapability):
    identifier = "fake-notify"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.messages: list[str] = []

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        self.messages.append(message)
        return {"delivered": True}
