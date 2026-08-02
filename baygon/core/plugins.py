"""Plugin Manager.

Loads provider implementations declared in ``baygon.yaml`` and registers
them in the Capability Registry. The core never imports a provider by
itself: every provider module path comes from the configuration, which
keeps the core free of any hard-coded provider.

A plugin failure is isolated: it is reported as an event and the rest of
the system keeps working (the capability is simply unavailable).
"""

from __future__ import annotations

import contextlib
import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

from baygon.capabilities.base import CapabilityImplementation
from baygon.core import events
from baygon.core.config import BaygonConfig, ProviderConfig
from baygon.core.errors import PluginError
from baygon.core.events import EventBus
from baygon.core.registry import CapabilityRegistry


def _load_class(spec: str) -> type[CapabilityImplementation]:
    """Resolve a ``package.module:ClassName`` plugin specification."""
    module_path, _, class_name = spec.partition(":")
    if not module_path or not class_name:
        raise PluginError(f"Invalid plugin specification {spec!r}, expected 'module:ClassName'")
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise PluginError(f"Cannot import plugin module {module_path!r}: {exc}") from exc
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise PluginError(f"Module {module_path!r} has no class {class_name!r}") from exc
    if not (isinstance(cls, type) and issubclass(cls, CapabilityImplementation)):
        raise PluginError(f"{spec!r} is not a CapabilityImplementation")
    return cls


@contextlib.contextmanager
def _importable(directory: Path | None) -> Iterator[None]:
    """Make a project's own directory importable while it loads.

    A project may ship an adapter next to its baygon.yaml. With several
    projects managed at once, no single PYTHONPATH can cover them all,
    so the directory is added only for the duration of the load and
    removed afterwards — projects never leak into each other.
    """
    if directory is None or str(directory) in sys.path:
        yield
        return
    sys.path.insert(0, str(directory))
    try:
        yield
    finally:
        with contextlib.suppress(ValueError):
            sys.path.remove(str(directory))


class PluginManager:
    def __init__(self, bus: EventBus, registry: CapabilityRegistry) -> None:
        self._bus = bus
        self._registry = registry
        self._project_dir = None
        self.failures: dict[str, str] = {}

    def load_from_config(self, config: BaygonConfig) -> None:
        # Paths declared by a project are relative to that project's file.
        self._project_dir = config.path.parent if config.path else None
        with _importable(self._project_dir):
            for provider in config.providers:
                self._load_provider(provider)
            # AI models are declared in their own block so that swapping a
            # model only ever touches the `ai` section of baygon.yaml.
            default_ai = config.ai.get("default")
            for name, entry in (config.ai.get("providers") or {}).items():
                if not isinstance(entry, dict) or "plugin" not in entry:
                    self.failures[name] = "ai provider must declare a 'plugin'"
                    continue
                self._load_provider(
                    ProviderConfig(
                        name=name,
                        type=str(entry.get("type", "ai")),
                        plugin=str(entry["plugin"]),
                        default=(name == default_ai),
                        options=entry.get("options") or {},
                    )
                )

    def _load_provider(self, provider: ProviderConfig) -> None:
        try:
            cls = _load_class(provider.plugin)
            implementation = cls(provider.options)
            # Assigned after construction so third-party plugins are free
            # to define their own __init__ signature.
            implementation.project_dir = self._project_dir
            if implementation.capability != provider.type:
                raise PluginError(
                    f"Provider {provider.name!r} is declared with type "
                    f"{provider.type!r} but the plugin provides "
                    f"{implementation.capability!r}"
                )
            self._registry.register(
                implementation, default=provider.default, name=provider.name
            )
        except Exception as exc:
            # Isolate the failure: record it, publish it, keep going.
            self.failures[provider.name] = str(exc)
            self._bus.publish(
                events.PLUGIN_FAILED,
                provider=provider.name,
                plugin=provider.plugin,
                error=str(exc),
            )
