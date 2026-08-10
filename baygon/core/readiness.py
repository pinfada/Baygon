"""What can actually be done on a project, and what is missing.

`capabilities` lists providers and `context` describes configuration;
neither answers the question an operator really has — *what works?*
Finding out by attempting an intention is a poor way to learn that
fourteen of sixteen were never possible.

The answer is deduced, not measured: each intention's plan is built,
and what it needs is compared against what the project declares and
allows. No provider is contacted, so the report stays instant (ENF-010)
and truthful even when every backend is down.
"""

from __future__ import annotations

from typing import Any

from baygon.core.config import BaygonConfig
from baygon.core.executor import _PERMISSION_BY_ACTION
from baygon.core.intent import IntentEngine
from baygon.core.registry import CapabilityRegistry


def _remedy(missing_capabilities: list[str], missing_permissions: list[str]) -> list[str]:
    """The line to add to baygon.yaml, named rather than alluded to."""
    remedy = [
        f"declare a provider with type: {capability} under 'providers' in baygon.yaml"
        for capability in missing_capabilities
    ]
    remedy += [
        f"declare 'permissions.{operation}: true' in baygon.yaml"
        for operation in missing_permissions
    ]
    return remedy


def build(
    config: BaygonConfig, registry: CapabilityRegistry, engine: IntentEngine,
    failures: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Readiness report for one project."""
    intents: list[dict[str, Any]] = []
    for name in engine.supported_intents():
        plan = engine.plan_for(name)
        missing_capabilities = sorted({
            step.capability for step in plan.steps
            if not registry.is_available(step.capability)
        })
        missing_permissions = sorted({
            operation for step in plan.steps
            if (operation := _PERMISSION_BY_ACTION.get((step.capability, step.action)))
            and not config.is_allowed(operation)
        })
        # A step that is HIGH without its own permission falls under the
        # production gate, which is a permission like any other.
        if any(
            step.risk.rank >= 2
            and (step.capability, step.action) not in _PERMISSION_BY_ACTION
            for step in plan.steps
        ) and not config.is_allowed("production"):
            missing_permissions = sorted(set(missing_permissions) | {"production"})
        ready = not missing_capabilities and not missing_permissions
        intents.append({
            "intent": name,
            "ready": ready,
            "capabilities": sorted({step.capability for step in plan.steps}),
            "missing_capabilities": missing_capabilities,
            "missing_permissions": missing_permissions,
            "remedy": [] if ready else _remedy(missing_capabilities, missing_permissions),
        })

    return {
        "project": config.project_name,
        "intents": intents,
        "ready_count": sum(1 for entry in intents if entry["ready"]),
        "total_count": len(intents),
        "commands": sorted(config.commands),
        "providers": [
            {"name": metadata["name"], "capability": capability,
             "implementation": metadata["identifier"], "state": metadata["state"]}
            for capability, implementations in registry.capabilities().items()
            for metadata in implementations
        ],
        # A provider that never loaded is the most invisible failure of
        # all: the capability is simply absent, with no reason given.
        "failures": dict(failures or {}),
    }
