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
        AICapability,
    )
}
