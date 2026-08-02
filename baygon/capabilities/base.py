"""Base classes and contracts for Baygon capabilities.

Every implementation:

- provides exactly one main capability;
- respects the contract (interface) of that capability;
- exposes metadata (identifier, version, author, license);
- never depends on another implementation.
"""

from __future__ import annotations

import abc
import enum
from typing import Any


class ImplementationState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    FAILED = "FAILED"
    DEPRECATED = "DEPRECATED"
    UNKNOWN = "UNKNOWN"


class CapabilityImplementation(abc.ABC):
    """Common base for every provider implementation.

    Subclasses set ``capability`` to the capability name they provide and
    implement the matching contract below.
    """

    #: Capability name provided by this implementation (e.g. "deployment").
    capability: str = ""
    #: Unique identifier of the implementation (e.g. "render", "github").
    identifier: str = ""
    version: str = "0.0.0"
    author: str = ""
    license: str = ""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.state = ImplementationState.UNKNOWN

    def health_check(self) -> bool:
        """Return True when the implementation is usable. Override if needed."""
        return True

    def metadata(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "version": self.version,
            "author": self.author,
            "license": self.license,
            "capability": self.capability,
            "state": self.state.value,
        }


class RepositoryCapability(CapabilityImplementation):
    """Source code management."""

    capability = "repository"

    @abc.abstractmethod
    def get_latest_commit(self, **params: Any) -> dict[str, Any]: ...

    @abc.abstractmethod
    def history(self, limit: int = 10, **params: Any) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    def diff(self, **params: Any) -> str: ...


class DeploymentCapability(CapabilityImplementation):
    """Application deployment. Baygon never deploys directly."""

    capability = "deployment"

    @abc.abstractmethod
    def deploy(self, environment: str, **params: Any) -> dict[str, Any]: ...

    @abc.abstractmethod
    def status(self, environment: str, **params: Any) -> dict[str, Any]: ...

    @abc.abstractmethod
    def rollback(self, environment: str, **params: Any) -> dict[str, Any]: ...


class LogsCapability(CapabilityImplementation):
    """Log consultation. Baygon never stores logs."""

    capability = "logs"

    @abc.abstractmethod
    def fetch(self, environment: str, since_hours: int = 1, **params: Any) -> list[str]: ...


class MetricsCapability(CapabilityImplementation):
    """Metrics consultation. Baygon never stores metrics."""

    capability = "metrics"

    @abc.abstractmethod
    def fetch(self, environment: str, **params: Any) -> dict[str, Any]: ...


class DatabaseCapability(CapabilityImplementation):
    """Database access through the provider's own mechanisms."""

    capability = "database"

    @abc.abstractmethod
    def info(self, environment: str, **params: Any) -> dict[str, Any]: ...


class SecretsCapability(CapabilityImplementation):
    """Secret access. Secrets are never stored in clear text by Baygon."""

    capability = "secrets"

    @abc.abstractmethod
    def get(self, name: str, **params: Any) -> str: ...


class NotificationCapability(CapabilityImplementation):
    """Notification delivery."""

    capability = "notification"

    @abc.abstractmethod
    def notify(self, message: str, **params: Any) -> dict[str, Any]: ...


class StorageCapability(CapabilityImplementation):
    """File management (chapter 8)."""

    capability = "storage"

    @abc.abstractmethod
    def list(self, prefix: str = "", **params: Any) -> list[dict[str, Any]]: ...


class SSHCapability(CapabilityImplementation):
    """Remote access (EF-010).

    Baygon never opens the interactive session itself: it returns the
    authorized connection command declared in configuration.
    """

    capability = "ssh"

    @abc.abstractmethod
    def command(self, environment: str, **params: Any) -> dict[str, Any]: ...


class WorkspaceCapability(CapabilityImplementation):
    """Development environment: executes the project's declared commands.

    The command lines come from the `commands` section of baygon.yaml;
    the core never knows them.
    """

    capability = "workspace"

    @abc.abstractmethod
    def execute(self, command: str, command_line: str, environment: str, **params: Any) -> dict[str, Any]: ...


class BackupCapability(CapabilityImplementation):
    """Backup of a project environment."""

    capability = "backup"

    @abc.abstractmethod
    def backup(self, environment: str, **params: Any) -> dict[str, Any]: ...


class RecoveryCapability(CapabilityImplementation):
    """Restoration. Destructive by nature: always requires validation."""

    capability = "recovery"

    @abc.abstractmethod
    def restore(self, environment: str, **params: Any) -> dict[str, Any]: ...


class DeveloperCapability(CapabilityImplementation):
    """Code modification by an orchestrated coding agent.

    Baygon never edits code itself: the agent (Claude Code, aider, ...)
    is a specialized tool like any other, and stays interchangeable.
    `feedback` carries the QA report of the previous failed attempt.
    """

    capability = "developer"

    @abc.abstractmethod
    def fix(self, description: str, feedback: str | None = None, **params: Any) -> dict[str, Any]: ...


class AICapability(CapabilityImplementation):
    """Reasoning. Optional: Baygon must stay fully usable without it."""

    capability = "ai"

    @abc.abstractmethod
    def complete(self, prompt: str, context: dict[str, Any] | None = None, **params: Any) -> str: ...


#: Contract expected for each capability name. The registry rejects an
#: implementation that does not honour the contract of its capability.
CAPABILITY_CONTRACTS: dict[str, type[CapabilityImplementation]] = {
    contract.capability: contract
    for contract in (
        RepositoryCapability,
        DeploymentCapability,
        LogsCapability,
        MetricsCapability,
        DatabaseCapability,
        SecretsCapability,
        NotificationCapability,
        SSHCapability,
        StorageCapability,
        WorkspaceCapability,
        DeveloperCapability,
        BackupCapability,
        RecoveryCapability,
        AICapability,
    )
}
