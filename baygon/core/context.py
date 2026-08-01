"""Context Engine.

Builds the context needed to reason about a project. It knows:

- what the project is;
- which providers are used;
- where metrics and logs come from;
- where secrets live (never their values);
- which permissions are available.

The Context Engine performs no action: it only prepares context.
"""

from __future__ import annotations

from typing import Any

from baygon.core.config import BaygonConfig
from baygon.core.registry import CapabilityRegistry


class ContextEngine:
    def __init__(self, config: BaygonConfig, registry: CapabilityRegistry) -> None:
        self._config = config
        self._registry = registry

    def build(self) -> dict[str, Any]:
        """Assemble the full project context from configuration and registry.

        Everything here is descriptive: no provider is contacted and no
        secret value is ever included, only where secrets are managed.
        """
        config = self._config
        capabilities = self._registry.capabilities()
        return {
            "project": {
                "name": config.project_name,
                "description": config.project.get("description", ""),
                "repository": config.project.get("repository", ""),
                "language": config.project.get("language", ""),
                "framework": config.project.get("framework", ""),
            },
            "environments": sorted(config.environments),
            "providers": [
                {
                    "name": provider.name,
                    "type": provider.type,
                    "plugin": provider.plugin,
                    "default": provider.default,
                }
                for provider in config.providers
            ],
            "capabilities": {
                name: [
                    {"identifier": impl["identifier"], "state": impl["state"]}
                    for impl in implementations
                ]
                for name, implementations in capabilities.items()
            },
            "observability": config.observability,
            "commands": sorted(config.commands),
            "permissions": {
                operation: bool(allowed)
                for operation, allowed in sorted(config.permissions.items())
            },
            "ai": {
                "default": self._config.ai.get("default"),
                "available": self._registry.is_available("ai"),
            },
        }
