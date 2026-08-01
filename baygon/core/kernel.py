"""Baygon Core.

The only mandatory component. It contains no business logic and knows no
provider: it wires the Config Loader, the Intent Engine, the Capability
Registry, the Plugin Manager and the Event Manager together.

Lifecycle:

    start -> read baygon.yaml -> validate -> load plugins -> ready
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from baygon.core import events
from baygon.core.audit import AuditJournal
from baygon.core.config import BaygonConfig, load_config
from baygon.core.errors import ValidationRequiredError
from baygon.core.events import EventBus
from baygon.core.executor import ExecutionEngine, ExecutionResult
from baygon.core.intent import IntentEngine, Plan
from baygon.core.plugins import PluginManager
from baygon.core.registry import CapabilityRegistry


class Kernel:
    def __init__(self, config: BaygonConfig, state_dir: str | Path | None = None) -> None:
        self.config = config
        self.bus = EventBus()
        self.registry = CapabilityRegistry(self.bus)
        self.plugins = PluginManager(self.bus, self.registry)
        self.intent_engine = IntentEngine(config, self.registry)
        self.executor = ExecutionEngine(config, self.registry, self.bus)
        base = Path(state_dir) if state_dir else (config.path.parent if config.path else Path("."))
        self.audit = AuditJournal(base / ".baygon")
        self._ready = False

    @classmethod
    def start(cls, config_path: str | Path, state_dir: str | Path | None = None) -> "Kernel":
        """Read baygon.yaml, validate it, load the plugins and become ready."""
        config = load_config(config_path)
        kernel = cls(config, state_dir=state_dir)
        kernel.plugins.load_from_config(config)
        kernel._ready = True
        kernel.bus.publish(events.PROJECT_OPENED, project=config.project_name)
        return kernel

    @property
    def ready(self) -> bool:
        return self._ready

    # ------------------------------------------------------------------
    # Public operations, used by every interface (terminal, API, ...)
    # ------------------------------------------------------------------

    def plan(self, text: str, source: str = "shell") -> Plan:
        plan = self.intent_engine.plan(text, source=source)
        self.bus.publish(
            events.PLAN_CREATED, plan=plan.id, intent=plan.intent.name, risk=plan.risk.value
        )
        return plan

    def run(self, text: str, approved: bool = False, source: str = "shell") -> ExecutionResult:
        plan = self.plan(text, source=source)
        return self.execute(plan, approved=approved)

    def execute(self, plan: Plan, approved: bool = False) -> ExecutionResult:
        try:
            result = self.executor.execute(plan, approved=approved)
        except ValidationRequiredError:
            self.audit.record(plan, None, status="suspended")
            raise
        self.audit.record(plan, result, status="success" if result.success else "failure")
        self.bus.publish(events.COMMAND_EXECUTED, plan=plan.id, success=result.success)
        return result

    def capabilities(self) -> dict[str, Any]:
        return self.registry.capabilities()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.audit.entries(limit=limit)
