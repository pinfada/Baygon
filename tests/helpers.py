"""Shared test fixtures: in-memory fake implementations and configs."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

from baygon.capabilities import (
    BackupCapability,
    DeploymentCapability,
    LogsCapability,
    MetricsCapability,
    NotificationCapability,
    RecoveryCapability,
    RepositoryCapability,
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


class FakeNotification(NotificationCapability):
    identifier = "fake-notify"

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__(config)
        self.messages: list[str] = []

    def notify(self, message: str, **params: Any) -> dict[str, Any]:
        self.messages.append(message)
        return {"delivered": True}
