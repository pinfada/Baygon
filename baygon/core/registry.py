"""Capability Registry.

Central catalogue of every capability and its implementations. The core
never uses an implementation directly: it always goes through the
registry.

Selection rules, in order:

1. explicitly requested implementation;
2. default implementation;
3. any compatible (ACTIVE) implementation;
4. error.
"""

from __future__ import annotations

from baygon.capabilities.base import (
    CAPABILITY_CONTRACTS,
    CapabilityImplementation,
    ImplementationState,
)
from baygon.core import events
from baygon.core.errors import CapabilityUnavailableError, PluginError
from baygon.core.events import EventBus


class CapabilityRegistry:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        # capability name -> implementation identifier -> implementation
        self._implementations: dict[str, dict[str, CapabilityImplementation]] = {}
        # capability name -> identifier of the default implementation
        self._defaults: dict[str, str] = {}

    def register(
        self,
        implementation: CapabilityImplementation,
        default: bool = False,
        name: str | None = None,
    ) -> None:
        """Validate then register one implementation.

        Discovery -> Validation -> Registration -> Activation -> Available.

        `name` is the key callers select with — the provider name from
        baygon.yaml. It defaults to the adapter's own identifier, which
        matters when one generic adapter backs several declarations
        (two endpoints of the same kind would otherwise collide).
        """
        capability = implementation.capability
        if not capability:
            raise PluginError(
                f"Implementation {type(implementation).__name__} declares no capability"
            )
        contract = CAPABILITY_CONTRACTS.get(capability)
        if contract is not None and not isinstance(implementation, contract):
            raise PluginError(
                f"Implementation {implementation.identifier!r} does not honour the "
                f"{contract.__name__} contract for capability {capability!r}"
            )
        if not implementation.identifier:
            raise PluginError(
                f"Implementation {type(implementation).__name__} declares no identifier"
            )

        try:
            healthy = implementation.health_check()
        except Exception as exc:
            implementation.state = ImplementationState.FAILED
            self._bus.publish(
                events.PROVIDER_FAILED,
                capability=capability,
                implementation=implementation.identifier,
                error=str(exc),
            )
            healthy = False
        else:
            implementation.state = (
                ImplementationState.ACTIVE if healthy else ImplementationState.FAILED
            )

        key = name or implementation.identifier
        self._implementations.setdefault(capability, {})[key] = implementation
        if default:
            self._defaults[capability] = key
        self._bus.publish(
            events.PLUGIN_LOADED,
            capability=capability,
            implementation=key,
            state=implementation.state.value,
        )

    def unregister(self, capability: str, identifier: str) -> None:
        self._implementations.get(capability, {}).pop(identifier, None)
        if self._defaults.get(capability) == identifier:
            del self._defaults[capability]

    def clear(self) -> None:
        """Remove every implementation (hot reload rebuilds the catalog)."""
        self._implementations.clear()
        self._defaults.clear()

    def capabilities(self) -> dict[str, list[dict[str, str]]]:
        """Expose available capabilities and their implementations."""
        return {
            capability: [{**impl.metadata(), "name": key} for key, impl in impls.items()]
            for capability, impls in sorted(self._implementations.items())
        }

    def is_available(self, capability: str) -> bool:
        return any(
            impl.state == ImplementationState.ACTIVE
            for impl in self._implementations.get(capability, {}).values()
        )

    def resolve(self, capability: str, requested: str | None = None) -> CapabilityImplementation:
        implementations = self._implementations.get(capability, {})
        if not implementations:
            raise CapabilityUnavailableError(capability, "no implementation registered")

        # 1. Explicitly requested implementation.
        if requested is not None:
            impl = implementations.get(requested)
            if impl is None:
                raise CapabilityUnavailableError(
                    capability, f"requested implementation {requested!r} is not registered"
                )
            if impl.state != ImplementationState.ACTIVE:
                raise CapabilityUnavailableError(
                    capability,
                    f"requested implementation {requested!r} is {impl.state.value}",
                )
            return self._selected(capability, impl)

        # 2. Default implementation.
        default_id = self._defaults.get(capability)
        if default_id is not None:
            impl = implementations.get(default_id)
            if impl is not None and impl.state == ImplementationState.ACTIVE:
                return self._selected(capability, impl)

        # 3. Any compatible implementation.
        for impl in implementations.values():
            if impl.state == ImplementationState.ACTIVE:
                return self._selected(capability, impl)

        # 4. Error.
        raise CapabilityUnavailableError(capability, "no ACTIVE implementation")

    def _selected(
        self, capability: str, impl: CapabilityImplementation
    ) -> CapabilityImplementation:
        self._bus.publish(
            events.IMPLEMENTATION_SELECTED,
            capability=capability,
            implementation=impl.identifier,
        )
        return impl
