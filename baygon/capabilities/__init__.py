"""Capability contracts.

A capability describes what can be done, never how. The core only knows
these contracts; implementations (providers) live outside the core and
are registered through the Capability Registry.
"""

from baygon.capabilities.base import (
    CAPABILITY_CONTRACTS,
    AICapability,
    BackupCapability,
    CapabilityImplementation,
    DatabaseCapability,
    DeploymentCapability,
    ImplementationState,
    LogsCapability,
    MetricsCapability,
    NotificationCapability,
    RecoveryCapability,
    RepositoryCapability,
    SecretsCapability,
    WorkspaceCapability,
)

__all__ = [
    "CAPABILITY_CONTRACTS",
    "AICapability",
    "BackupCapability",
    "CapabilityImplementation",
    "DatabaseCapability",
    "DeploymentCapability",
    "ImplementationState",
    "LogsCapability",
    "MetricsCapability",
    "NotificationCapability",
    "RecoveryCapability",
    "RepositoryCapability",
    "SecretsCapability",
    "WorkspaceCapability",
]
