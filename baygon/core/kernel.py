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
from baygon.core.context import ContextEngine
from baygon.core.errors import BaygonError, ValidationRequiredError
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
        self.context_engine = ContextEngine(config, self.registry)
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

    def execute(
        self,
        plan: Plan,
        approved: bool = False,
        completed: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        try:
            result = self.executor.execute(plan, approved=approved, completed=completed)
        except ValidationRequiredError:
            self.audit.record(plan, None, status="suspended")
            raise
        self.audit.record(plan, result, status="success" if result.success else "failure")
        self.bus.publish(events.COMMAND_EXECUTED, plan=plan.id, success=result.success)
        return result

    def resume(self, plan_id: str | None = None, approved: bool = False) -> ExecutionResult:
        """Resume the last failed execution (ENF-017).

        Steps that already succeeded are not re-executed: their recorded
        outputs are reused and execution restarts at the failed step.
        """
        entry = self._last_failure(plan_id)
        if entry is None:
            target = f" for plan {plan_id!r}" if plan_id else ""
            raise BaygonError(f"nothing to resume{target}: no failed execution recorded")
        plan = self.intent_engine.plan(
            entry["input"], source=entry["plan"]["intent"].get("source", "shell")
        )
        completed = {
            step["id"]: step["output"]
            for step in entry["result"]["steps"]
            if step["success"]
        }
        return self.execute(plan, approved=approved, completed=completed)

    def _last_failure(self, plan_id: str | None) -> dict[str, Any] | None:
        for entry in reversed(self.audit.entries(limit=1000)):
            if entry.get("status") != "failure" or not entry.get("result"):
                continue
            if plan_id is not None and entry["plan"]["id"] != plan_id:
                continue
            return entry
        return None

    def capabilities(self) -> dict[str, Any]:
        return self.registry.capabilities()

    def context(self) -> dict[str, Any]:
        return self.context_engine.build()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.audit.entries(limit=limit)
