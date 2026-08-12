"""Baygon Core.

The only mandatory component. It contains no business logic and knows no
provider: it wires the Config Loader, the Intent Engine, the Capability
Registry, the Plugin Manager and the Event Manager together.

Lifecycle:

    start -> read baygon.yaml -> validate -> load plugins -> ready
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from baygon.core import events, readiness
from baygon.core.audit import AuditJournal
from baygon.core.config import BaygonConfig, load_config
from baygon.core.context import ContextEngine
from baygon.core.errors import BaygonError, ValidationRequiredError
from baygon.core.events import EventBus
from baygon.core.executor import ExecutionEngine, ExecutionResult
from baygon.core.intent import IntentEngine, Plan, Step
from baygon.core.plugins import PluginManager
from baygon.core.registry import CapabilityRegistry


def _plan_with_feedback(plan: Plan, feedback: str) -> Plan:
    """Copy of the plan with the failure report injected into the
    feedback step's parameters. Same id: it is the same intention.

    Every other field of every step is carried over untouched — in
    particular the explicitly requested implementation, which a retry
    round must never silently trade for the default one.
    """
    steps = []
    for step in plan.steps:
        parameters = dict(step.parameters)
        if step.id == plan.feedback_step:
            parameters["feedback"] = feedback
        steps.append(replace(step, parameters=parameters, depends_on=list(step.depends_on)))
    return replace(plan, steps=steps)


def _briefed(plan: Plan, description: str, origin: str) -> Plan:
    """Copy of the plan with the description injected into its developer
    steps, and the origin of that description told first (Article 8)."""
    steps = [
        replace(step, parameters={**step.parameters, "description": description})
        if step.capability == "developer" else step
        for step in plan.steps
    ]
    return replace(plan, steps=steps, reasoning=[origin, *plan.reasoning])


def _compact(output: Any) -> str:
    """One journal output, flattened and bounded for a briefing line."""
    text = " ".join(str(output).split())
    return text[:500] + (" …" if len(text) > 500 else "")


def _carry_descriptions(plan: Plan, recorded: dict[str, Any]) -> Plan:
    """Rebuilt developer steps take back the description that was run.

    A briefed description ("corrige le dernier incident/diagnostic")
    belongs to the plan the user approved, not to the words that
    produced it: rebuilding from the words alone would hand the agent
    the phrase — or a description drawn from a journal that has moved
    on since the approval. For an ordinary fix the recorded and rebuilt
    descriptions are identical, so this changes nothing.
    """
    by_id = {step["id"]: step for step in recorded["steps"]}
    steps = []
    for step in plan.steps:
        old = by_id.get(step.id)
        if (
            step.capability == "developer"
            and old is not None
            and (old["capability"], old["action"]) == (step.capability, step.action)
            and "description" in old["parameters"]
        ):
            step = replace(
                step,
                parameters={**step.parameters,
                            "description": old["parameters"]["description"]},
            )
        steps.append(step)
    return replace(plan, steps=steps)


def _reusable(plan: Plan, recorded: list[dict[str, Any]]) -> dict[str, Any]:
    """Recorded outputs that still belong to a step of the rebuilt plan.

    A result belongs to a step, not to an identifier. Between the
    failure and the resume, ``baygon.yaml`` may have changed and the
    rebuilt plan may no longer be step-for-step identical; feeding a
    stale output into a step that is not the one that produced it would
    be worse than simply running that step again.
    """
    expected = {step.id: (step.capability, step.action) for step in plan.steps}
    return {
        step["id"]: step["output"]
        for step in recorded
        if step["success"] and expected.get(step["id"]) == (step["capability"], step["action"])
    }


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

    def reload(self) -> None:
        """Hot reload (chapter 10): re-read baygon.yaml and rebuild the
        capability catalog without restarting Baygon.

        The new file is validated first — if it is invalid the running
        state is left untouched. The event bus and the audit journal
        survive the reload.
        """
        if self.config.path is None:
            raise BaygonError("cannot reload: no configuration file backs this kernel")
        config = load_config(self.config.path)  # invalid file -> raise, keep old state
        self.registry.clear()
        self.plugins = PluginManager(self.bus, self.registry)
        self.plugins.load_from_config(config)
        self.config = config
        self.intent_engine = IntentEngine(config, self.registry)
        self.executor = ExecutionEngine(config, self.registry, self.bus)
        self.context_engine = ContextEngine(config, self.registry)
        self.bus.publish(events.PROJECT_RELOADED, project=config.project_name)

    # ------------------------------------------------------------------
    # Public operations, used by every interface (terminal, API, ...)
    # ------------------------------------------------------------------

    def plan(
        self,
        text: str,
        source: str = "shell",
        ai: bool = True,
        ai_model: str | None = None,
    ) -> Plan:
        plan = self.intent_engine.plan(text, source=source, ai=ai, ai_model=ai_model)
        # Only a fix has a developer step to brief: on any other intention
        # the phrasing is just context ("pourquoi ce dernier incident ?").
        if plan.intent.name == "FixBug":
            if plan.intent.parameters.get("from_last_incident"):
                plan = self._describe_last_incident(plan)
            elif plan.intent.parameters.get("from_last_diagnosis"):
                plan = self._describe_last_diagnosis(plan)
        self.bus.publish(
            events.PLAN_CREATED, plan=plan.id, intent=plan.intent.name, risk=plan.risk.value
        )
        return plan

    def _describe_last_incident(self, plan: Plan) -> Plan:
        """Replace the description with what actually failed.

        The Intent Engine recognised "the last incident" but cannot
        know what it was: it reads language, never state. The journal
        is the kernel's, so the kernel fills it in — the agent then
        receives the cause, the step and the intention that was being
        served, instead of the words the operator typed.
        """
        entry = self._last_failure(None)
        if entry is None:
            raise BaygonError(
                "no failure recorded: there is no incident to hand over. "
                "Describe the bug instead, or run the intention that fails first"
            )
        failure = entry["result"]["failure"] or {}
        step = next(
            (s for s in entry["result"]["steps"] if s["id"] == failure.get("step")), {}
        )
        description = (
            f"Corrige l'incident suivant, survenu en exécutant l'intention "
            f"{entry['intent']} (« {entry['input']} ») :\n"
            f"- étape {failure.get('step')} : {step.get('capability')}."
            f"{step.get('action')}\n"
            f"- cause : {failure.get('cause')}\n"
            f"Corrige la cause dans le code du projet, pas le symptôme."
        )
        return _briefed(
            plan,
            description,
            f"Description reprise du dernier incident journalisé "
            f"({entry['intent']}, étape {failure.get('step')})",
        )

    def _describe_last_diagnosis(self, plan: Plan) -> Plan:
        """Replace the description with what the last diagnosis found.

        The other side of the incident handoff: a Diagnose that
        *succeeded* named a probable cause, and the operator should not
        have to read it on one screen and retype it on another. The
        model's analysis is preferred; a diagnosis made without AI still
        hands over its raw evidence (EF-014: degraded, never broken).
        """
        entry = self._last_diagnosis()
        if entry is None:
            raise BaygonError(
                "no diagnosis recorded: there is nothing to hand over. "
                "Run a diagnosis first (e.g. « pourquoi la production est lente ? »)"
            )
        recorded = entry["result"]["steps"]
        # A model can succeed and still say nothing (a tool-use-only
        # response): an empty answer must not shadow the gathered evidence.
        analysis = next(
            (s["output"] for s in recorded
             if s["capability"] == "ai" and s["success"] and s["output"]),
            None,
        )
        if analysis is None:
            evidence = "\n".join(
                f"- {s['capability']}.{s['action']} : {_compact(s['output'])}"
                for s in recorded if s["success"]
            )
            body = f"Constats bruts du diagnostic :\n{evidence}"
        else:
            body = f"Diagnostic établi par le modèle :\n{analysis}"
        description = (
            f"Corrige la cause du problème décrit par ce diagnostic, obtenu en "
            f"répondant à « {entry['input']} » :\n{body}\n"
            f"Corrige la cause dans le code du projet, pas le symptôme."
        )
        return _briefed(
            plan,
            description,
            "Description reprise du dernier diagnostic journalisé "
            + ("(analyse du modèle)" if analysis else "(constats bruts, sans IA)"),
        )

    def run(
        self,
        text: str,
        approved: bool = False,
        source: str = "shell",
        ai: bool = True,
        ai_model: str | None = None,
    ) -> ExecutionResult:
        plan = self.plan(text, source=source, ai=ai, ai_model=ai_model)
        return self.execute(plan, approved=approved)

    def models(self) -> list[dict[str, Any]]:
        """Models this session may choose from, with their freshness.

        The configuration declares what is available; the caller picks
        among them (Registry rule 1). Freshness is best effort.
        """
        entries = []
        for metadata in self.capabilities().get("ai", []):
            name = metadata["name"]
            entry = {"name": name, "adapter": metadata["identifier"],
                     "state": metadata["state"], "model": None,
                     "up_to_date": None, "known_models": [], "reachable": None}
            try:
                described = self.registry.resolve("ai", requested=name).describe()
            except Exception:
                entries.append(entry)  # an unavailable model is still worth listing
                continue
            entry.update({k: v for k, v in described.items() if k != "identifier"})
            entries.append(entry)
        return entries

    def execute(
        self,
        plan: Plan,
        approved: bool = False,
        completed: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        """Execute a plan, honouring its bounded retry policy.

        When the plan declares `max_rounds` > 1 and a `feedback_step`, a
        failed round is retried with the failure report injected as
        feedback to that step — the Dev -> QA correction loop. Every
        round is audited.
        """
        attempt = 0
        current = plan
        while True:
            attempt += 1
            try:
                result = self.executor.execute(
                    current, approved=approved,
                    completed=completed if attempt == 1 else None,
                )
            except ValidationRequiredError:
                self.audit.record(plan, None, status="suspended")
                raise
            self.audit.record(current, result, status="success" if result.success else "failure")
            self.bus.publish(events.COMMAND_EXECUTED, plan=current.id, success=result.success)
            if (
                result.success
                or plan.feedback_step is None
                or attempt >= max(1, plan.max_rounds)
            ):
                break
            feedback = (result.failure or {}).get("cause", "previous round failed")
            current = _plan_with_feedback(plan, str(feedback))
        if not result.success:
            self._notify_failure(plan, result)
        return result

    def _notify_failure(self, plan: Plan, result: ExecutionResult) -> None:
        """Best-effort failure notification (ENF-008): a failed plan is an
        event the team should see. Never breaks the structured result."""
        try:
            notifier = self.registry.resolve("notification")
        except BaygonError:
            return
        failure = result.failure or {}
        message = (
            f"[baygon] plan {plan.id} ({plan.intent.name}) failed at step "
            f"{failure.get('step')}: {failure.get('cause')}"
        )
        try:
            notifier.notify(message)
        except Exception:
            # An unreachable notifier must never mask the real failure.
            return

    def resume(self, plan_id: str | None = None, approved: bool = False) -> ExecutionResult:
        """Resume the last failed execution (ENF-017).

        Steps that already succeeded are not re-executed: their recorded
        outputs are reused and execution restarts at the failed step.

        The plan is rebuilt with the session options it was built with,
        so resuming replays the intention the user approved — a run made
        without AI never grows an AI step on resume (EF-014).
        """
        entry = self._last_failure(plan_id)
        if entry is None:
            target = f" for plan {plan_id!r}" if plan_id else ""
            raise BaygonError(f"nothing to resume{target}: no failed execution recorded")
        recorded = entry["plan"]
        session = recorded.get("session") or {}
        plan = self.intent_engine.plan(
            entry["input"],
            source=recorded["intent"].get("source", "shell"),
            ai=bool(session.get("ai", True)),
            ai_model=session.get("ai_model"),
        )
        plan = _carry_descriptions(plan, recorded)
        return self.execute(
            plan, approved=approved, completed=_reusable(plan, entry["result"]["steps"])
        )

    def _last_diagnosis(self) -> dict[str, Any] | None:
        for entry in reversed(self.audit.entries(limit=1000)):
            if (
                entry.get("intent") == "Diagnose"
                and entry.get("status") == "success"
                and entry.get("result")
            ):
                return entry
        return None

    def _last_failure(self, plan_id: str | None) -> dict[str, Any] | None:
        for entry in reversed(self.audit.entries(limit=1000)):
            if entry.get("status") != "failure" or not entry.get("result"):
                continue
            if plan_id is not None and entry["plan"]["id"] != plan_id:
                continue
            return entry
        return None

    def readiness(self) -> dict[str, Any]:
        """What can be done on this project, and what is missing.

        Deduced from the configuration alone: no provider is contacted,
        so the answer is instant and stays truthful even when every
        backend is down.
        """
        return readiness.build(
            self.config, self.registry, self.intent_engine, self.plugins.failures
        )

    def capabilities(self) -> dict[str, Any]:
        return self.registry.capabilities()

    def context(self) -> dict[str, Any]:
        return self.context_engine.build()

    def history(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.audit.entries(limit=limit)
