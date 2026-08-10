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
import re
import time
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
    ("review", "publish"): "publish",
    ("service", "restart"): "restart",
}


@dataclass
class StepResult:
    step: Step
    success: bool
    output: Any = None
    error: str | None = None
    #: Start, end and duration of the step (ENF-008).
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    #: True when the output was reused from a previous execution rather
    #: than recomputed — it cost no time and must not claim otherwise.
    reused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.step.id,
            "capability": self.step.capability,
            "action": self.step.action,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "reused": self.reused,
        }


@dataclass
class ExecutionResult:
    plan: Plan
    success: bool
    started_at: str
    finished_at: str
    steps: list[StepResult] = field(default_factory=list)
    failure: dict[str, Any] | None = None
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan": self.plan.id,
            "success": self.success,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "steps": [step.to_dict() for step in self.steps],
            "failure": self.failure,
        }


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _elapsed_ms(since: float) -> float:
    """Milliseconds since a monotonic mark, rounded to the microsecond.

    A monotonic clock is used rather than the wall clock so a system
    time adjustment can never report a negative duration.
    """
    return round((time.monotonic() - since) * 1000, 3)


#: `{{step_id.field}}` in a string parameter is replaced by that field of
#: the referenced step's output (chapter 9: reuse available results).
_REFERENCE = re.compile(r"\{\{(\w+)\.(\w+)\}\}")


def _resolve_references(parameters: dict[str, Any], outputs: dict[str, Any]) -> dict[str, Any]:
    def substitute(match: re.Match[str]) -> str:
        step_id, field = match.group(1), match.group(2)
        source = outputs.get(step_id)
        if isinstance(source, dict) and field in source:
            return str(source[field])
        return ""

    return {
        key: (_REFERENCE.sub(substitute, value) if isinstance(value, str) else value)
        for key, value in parameters.items()
    }


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
        mark = time.monotonic()
        ordered = self._ordered(plan.steps)
        self._bus.publish(events.EXECUTION_STARTED, plan=plan.id, steps=len(ordered))
        results: list[StepResult] = []
        outputs: dict[str, Any] = {}
        completed = completed or {}

        for step in ordered:
            if step.id in completed:
                output = completed[step.id]
                instant = _now()
                results.append(StepResult(
                    step=step, success=True, output=output, reused=True,
                    started_at=instant, finished_at=instant, duration_ms=0.0,
                ))
                outputs[step.id] = output
                self._bus.publish(
                    events.STEP_FINISHED, step=step.id, capability=step.capability,
                    action=step.action, success=True, reused=True, duration_ms=0.0,
                )
                continue
            result, options = self._run_step(step, outputs)
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
                    duration_ms=_elapsed_ms(mark),
                )
                self._bus.publish(
                    events.EXECUTION_FINISHED, plan=plan.id, success=False,
                    duration_ms=execution.duration_ms,
                )
                return execution
            outputs[step.id] = result.output

        execution = ExecutionResult(
            plan=plan, success=True, started_at=started, finished_at=_now(),
            steps=results, duration_ms=_elapsed_ms(mark),
        )
        self._bus.publish(
            events.EXECUTION_FINISHED, plan=plan.id, success=True,
            duration_ms=execution.duration_ms,
        )
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
        if operation:
            # The step declares its own permission: it governs the step,
            # the production gate below does not also apply.
            return
        if step.risk is RiskLevel.HIGH and not self._config.is_allowed("production"):
            raise StepExecutionError(
                step.id,
                "production operations are not allowed by the project permissions",
                ["declare 'permissions.production: true' in baygon.yaml"],
            )

    def _run_step(
        self, step: Step, outputs: dict[str, Any]
    ) -> tuple[StepResult, list[str] | None]:
        """Check, run and time one step.

        Returns the result and, when the step was refused for lack of a
        permission, the follow-up actions that would unblock it. Start
        and end are published either way: a refusal is as observable as
        a run (ENF-008).
        """
        self._bus.publish(
            events.STEP_STARTED, step=step.id, capability=step.capability,
            action=step.action,
        )
        started, mark = _now(), time.monotonic()
        options: list[str] | None = None
        try:
            self._check_permission(step)
            implementation = self._registry.resolve(
                step.capability, requested=step.implementation
            )
            action = getattr(implementation, step.action, None)
            if action is None or not callable(action):
                raise CapabilityUnavailableError(
                    step.capability,
                    f"implementation {implementation.identifier!r} has no action {step.action!r}",
                )
            parameters = _resolve_references(dict(step.parameters), outputs)
            if step.depends_on:
                # Reuse results already available from previous steps.
                parameters["context"] = {dep: outputs.get(dep) for dep in step.depends_on}
            output = action(**parameters)
            result = StepResult(step=step, success=True, output=output)
        except StepExecutionError as exc:
            # Refused before anything was contacted: the cause names the
            # missing permission and the options say how to grant it.
            result = StepResult(step=step, success=False, error=exc.cause)
            options = exc.options
        except Exception as exc:
            result = StepResult(step=step, success=False, error=str(exc))
        result.started_at = started
        result.finished_at = _now()
        result.duration_ms = _elapsed_ms(mark)
        self._bus.publish(
            events.STEP_FINISHED, step=step.id, capability=step.capability,
            action=step.action, success=result.success, duration_ms=result.duration_ms,
        )
        return result, options

    def _failure_options(self, step: Step) -> list[str]:
        options = ["retry the step", "abort the intention"]
        implementations = self._registry.capabilities().get(step.capability, [])
        if len(implementations) > 1:
            options.append("retry with another implementation")
        return options
