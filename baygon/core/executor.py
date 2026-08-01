"""Execution Engine.

Executes a plan produced by the Intent Engine:

- resolves each step's capability through the registry;
- checks permissions declared in ``baygon.yaml``;
- suspends plans that require validation until explicitly approved;
- reuses results already available (a step result is computed once);
- interrupts the plan on failure and reports the failed step, the cause
  and the possible follow-up actions.

A provider error never stops Baygon itself: it is captured and returned
as a structured result.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any

from baygon.core import events
from baygon.core.config import BaygonConfig
from baygon.core.errors import (
    CapabilityUnavailableError,
    StepExecutionError,
    ValidationRequiredError,
)
from baygon.core.events import EventBus
from baygon.core.intent import Plan, RiskLevel, Step
from baygon.core.registry import CapabilityRegistry

#: Operations that must be explicitly allowed in the `permissions` section.
_PERMISSION_BY_ACTION = {
    ("deployment", "deploy"): "deploy",
    ("deployment", "rollback"): "deploy",
    ("database", "info"): "database",
    ("ssh", "command"): "ssh",
}


@dataclass
class StepResult:
    step: Step
    success: bool
    output: Any = None
    error: str | None = None


@dataclass
class ExecutionResult:
    plan: Plan
    success: bool
    started_at: str
    finished_at: str
    steps: list[StepResult] = field(default_factory=list)
    failure: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.id,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [
                {
                    "id": r.step.id,
                    "capability": r.step.capability,
                    "action": r.step.action,
                    "success": r.success,
                    "output": r.output,
                    "error": r.error,
                }
                for r in self.steps
            ],
            "failure": self.failure,
        }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ExecutionEngine:
    def __init__(self, config: BaygonConfig, registry: CapabilityRegistry, bus: EventBus) -> None:
        self._config = config
        self._registry = registry
        self._bus = bus

    def execute(
        self,
        plan: Plan,
        approved: bool = False,
        completed: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Run a plan; `completed` maps already-successful step ids to their
        recorded outputs, which are reused instead of re-executing (ENF-017)."""
        if plan.requires_validation and not approved:
            self._bus.publish(events.PLAN_SUSPENDED, plan=plan.id, risk=plan.risk.value)
            raise ValidationRequiredError(plan.id)

        started = _now()
        self._bus.publish(events.EXECUTION_STARTED, plan=plan.id)
        results: list[StepResult] = []
        outputs: dict[str, Any] = {}
        completed = completed or {}

        for step in self._ordered(plan.steps):
            if step.id in completed:
                output = completed[step.id]
                results.append(StepResult(step=step, success=True, output=output))
                outputs[step.id] = output
                self._bus.publish(
                    events.STEP_FINISHED, step=step.id, capability=step.capability,
                    success=True, reused=True,
                )
                continue
            options: list[str] | None = None
            try:
                self._check_permission(step)
            except StepExecutionError as exc:
                result = StepResult(step=step, success=False, error=exc.cause)
                options = exc.options
            else:
                result = self._run_step(step, outputs)
            results.append(result)
            if not result.success:
                failure = {
                    "step": step.id,
                    "cause": result.error,
                    "options": options or self._failure_options(step),
                }
                self._bus.publish(
                    events.PROVIDER_FAILED,
                    plan=plan.id,
                    step=step.id,
                    capability=step.capability,
                    error=result.error,
                )
                execution = ExecutionResult(
                    plan=plan, success=False, started_at=started,
                    finished_at=_now(), steps=results, failure=failure,
                )
                self._bus.publish(events.EXECUTION_FINISHED, plan=plan.id, success=False)
                return execution
            outputs[step.id] = result.output

        execution = ExecutionResult(
            plan=plan, success=True, started_at=started, finished_at=_now(), steps=results
        )
        self._bus.publish(events.EXECUTION_FINISHED, plan=plan.id, success=True)
        return execution

    # ------------------------------------------------------------------

    def _ordered(self, steps: list[Step]) -> list[Step]:
        """Order steps so that every dependency runs before its dependents."""
        by_id = {step.id: step for step in steps}
        ordered: list[Step] = []
        visited: set[str] = set()

        def visit(step: Step, chain: tuple[str, ...]) -> None:
            if step.id in visited:
                return
            if step.id in chain:
                raise StepExecutionError(step.id, "circular dependency", ["fix the plan"])
            for dep in step.depends_on:
                if dep not in by_id:
                    raise StepExecutionError(step.id, f"unknown dependency {dep!r}", ["fix the plan"])
                visit(by_id[dep], chain + (step.id,))
            visited.add(step.id)
            ordered.append(step)

        for step in steps:
            visit(step, ())
        return ordered

    def _check_permission(self, step: Step) -> None:
        operation = _PERMISSION_BY_ACTION.get((step.capability, step.action))
        if operation and not self._config.is_allowed(operation):
            raise StepExecutionError(
                step.id,
                f"operation {operation!r} is not allowed by the project permissions",
                [f"declare 'permissions.{operation}: true' in baygon.yaml"],
            )
        if step.risk is RiskLevel.HIGH and not self._config.is_allowed("production"):
            raise StepExecutionError(
                step.id,
                "production operations are not allowed by the project permissions",
                ["declare 'permissions.production: true' in baygon.yaml"],
            )

    def _run_step(self, step: Step, outputs: dict[str, Any]) -> StepResult:
        self._bus.publish(events.STEP_STARTED, step=step.id, capability=step.capability)
        try:
            implementation = self._registry.resolve(step.capability)
            action = getattr(implementation, step.action, None)
            if action is None or not callable(action):
                raise CapabilityUnavailableError(
                    step.capability,
                    f"implementation {implementation.identifier!r} has no action {step.action!r}",
                )
            parameters = dict(step.parameters)
            if step.depends_on:
                # Reuse results already available from previous steps.
                parameters["context"] = {dep: outputs.get(dep) for dep in step.depends_on}
            output = action(**parameters)
            result = StepResult(step=step, success=True, output=output)
        except Exception as exc:
            result = StepResult(step=step, success=False, error=str(exc))
        self._bus.publish(
            events.STEP_FINISHED, step=step.id, capability=step.capability, success=result.success
        )
        return result

    def _failure_options(self, step: Step) -> list[str]:
        options = ["retry the step", "abort the intention"]
        implementations = self._registry.capabilities().get(step.capability, [])
        if len(implementations) > 1:
            options.append("retry with another implementation")
        return options
