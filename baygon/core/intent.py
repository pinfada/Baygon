"""Intent Engine.

The Intent Engine turns a user intention into an execution plan.
It thinks; it never acts:

- it contacts no provider;
- it calls no AI model;
- it only produces an explainable, deterministic plan.

Resolution is rule-based, so every essential command works without any
AI model (EF-014). Given an identical context (same input, same
configuration, same available capabilities) the produced plan is
identical.
"""

from __future__ import annotations

import enum
import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from baygon.core.config import BaygonConfig
from baygon.core.errors import UnknownIntentError
from baygon.core.registry import CapabilityRegistry


class RiskLevel(str, enum.Enum):
    LOW = "LOW"            # read only
    MEDIUM = "MEDIUM"      # reversible modification
    HIGH = "HIGH"          # production modification
    CRITICAL = "CRITICAL"  # destructive action

    @property
    def rank(self) -> int:
        return ["LOW", "MEDIUM", "HIGH", "CRITICAL"].index(self.value)


#: Risk levels that suspend the plan until explicit validation.
VALIDATION_THRESHOLD = RiskLevel.HIGH


@dataclass(frozen=True)
class Intent:
    """A normalized intention, whatever the input form was."""

    name: str
    parameters: dict[str, Any]
    raw_input: str
    source: str = "shell"


@dataclass
class Step:
    id: str
    capability: str
    action: str
    parameters: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    risk: RiskLevel = RiskLevel.LOW

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "capability": self.capability,
            "action": self.action,
            "parameters": self.parameters,
            "depends_on": self.depends_on,
            "risk": self.risk.value,
        }


@dataclass
class Plan:
    id: str
    intent: Intent
    steps: list[Step]
    reasoning: list[str]
    #: Bounded retry policy: how many times the whole plan may run.
    max_rounds: int = 1
    #: Step that receives the previous round's failure report as feedback.
    feedback_step: str | None = None

    @property
    def risk(self) -> RiskLevel:
        if not self.steps:
            return RiskLevel.LOW
        return max((step.risk for step in self.steps), key=lambda r: r.rank)

    @property
    def requires_validation(self) -> bool:
        return self.risk.rank >= VALIDATION_THRESHOLD.rank

    def explain(self) -> str:
        """Answer the question: why this plan?"""
        lines = [
            f"Intention: {self.intent.name}",
            f"Input: {self.intent.raw_input!r}",
            f"Overall risk: {self.risk.value}"
            + (" (validation required)" if self.requires_validation else ""),
            "Reasoning:",
        ]
        lines += [f"  - {reason}" for reason in self.reasoning]
        lines.append("Steps:")
        for step in self.steps:
            deps = f" (after {', '.join(step.depends_on)})" if step.depends_on else ""
            lines.append(
                f"  {step.id}. [{step.risk.value}] {step.capability}.{step.action}"
                f" {step.parameters}{deps}"
            )
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "intent": {
                "name": self.intent.name,
                "parameters": self.intent.parameters,
                "raw_input": self.intent.raw_input,
                "source": self.intent.source,
            },
            "risk": self.risk.value,
            "requires_validation": self.requires_validation,
            "max_rounds": self.max_rounds,
            "feedback_step": self.feedback_step,
            "reasoning": self.reasoning,
            "steps": [step.to_dict() for step in self.steps],
        }


_ENVIRONMENTS = ("production", "staging", "development")

# Deterministic resolution rules, evaluated in order. First match wins.
_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("DeployProject", re.compile(r"\b(deploy|d[ée]ploie[rs]?)\b", re.IGNORECASE)),
    ("RollbackDeployment", re.compile(r"\b(rollback|reviens|annule le d[ée]ploiement)\b", re.IGNORECASE)),
    ("ProposeChanges", re.compile(r"\b(propose[rs]?|revue|review|pull request|merge request|pr)\b", re.IGNORECASE)),
    ("FixBug", re.compile(r"\b(r[ée]sous|corrige[rs]?|r[ée]pare[rs]?|fix)\b", re.IGNORECASE)),
    ("BackupProject", re.compile(r"\b(backup|sauvegarde\w*)\b", re.IGNORECASE)),
    ("RestoreProject", re.compile(r"\b(restore|restaure\w*|restauration)\b", re.IGNORECASE)),
    ("OpenConsole", re.compile(r"\b(ssh|consoles?|terminal)\b", re.IGNORECASE)),
    ("ShowDatabase", re.compile(r"\b(base de donn[ée]es|database|db|postgres|psql)\b", re.IGNORECASE)),
    ("ShowStorage", re.compile(r"\b(stockage|storage|s3|fichiers?|files?)\b", re.IGNORECASE)),
    # Diagnosis comes before the single-source reads: "Pourquoi la
    # production est lente ?" is a full diagnosis (chapter 4), even
    # though it also mentions slowness.
    ("Diagnose", re.compile(r"\b(diagnosti\w*|incident|analyse[rs]?|pourquoi|why)\b", re.IGNORECASE)),
    ("ShowLogs", re.compile(r"\b(logs?|journaux|erreurs?|errors?)\b", re.IGNORECASE)),
    ("ShowMetrics", re.compile(r"\b(metrics?|m[ée]triques?|performances?|lente?s?)\b", re.IGNORECASE)),
    ("ShowStatus", re.compile(r"\b(status|statut|[ée]tat)\b", re.IGNORECASE)),
    ("ShowHistory", re.compile(r"\b(historique|history|commits?)\b", re.IGNORECASE)),
]

_HOURS = re.compile(r"(\d+)\s*(?:h|heures?|hours?)", re.IGNORECASE)


class IntentEngine:
    """Builds plans. Never executes anything."""

    def __init__(self, config: BaygonConfig, registry: CapabilityRegistry) -> None:
        self._config = config
        self._registry = registry

    # ------------------------------------------------------------------
    # Intention resolution
    # ------------------------------------------------------------------

    def supported_intents(self) -> list[str]:
        return [name for name, _ in _RULES]

    def resolve(self, text: str, source: str = "shell") -> Intent:
        """Convert any input form into a single normalized intention."""
        cleaned = text.strip()
        if not cleaned:
            raise UnknownIntentError(text, self.supported_intents())
        for name, pattern in _RULES:
            if pattern.search(cleaned):
                return Intent(
                    name=name,
                    parameters=self._extract_parameters(cleaned),
                    raw_input=cleaned,
                    source=source,
                )
        # Commands declared in baygon.yaml resolve without being coded
        # here: Baygon knows them through the configuration only.
        for command in sorted(self._config.commands):
            if re.search(rf"\b{re.escape(str(command))}\b", cleaned, re.IGNORECASE):
                parameters = self._extract_parameters(cleaned)
                parameters["command"] = str(command)
                return Intent(
                    name="RunCommand",
                    parameters=parameters,
                    raw_input=cleaned,
                    source=source,
                )
        raise UnknownIntentError(text, self.supported_intents())

    def _extract_parameters(self, text: str) -> dict[str, Any]:
        params: dict[str, Any] = {}
        lowered = text.lower()
        for env in _ENVIRONMENTS:
            if env in lowered or (env == "development" and "dev" in lowered.split()):
                params["environment"] = env
                break
        else:
            params["environment"] = "development"
        hours = _HOURS.search(text)
        if hours:
            params["since_hours"] = int(hours.group(1))
        project = self._config.project_name
        if project.lower() in lowered:
            params["project"] = project
        return params

    # ------------------------------------------------------------------
    # Plan construction
    # ------------------------------------------------------------------

    def plan(self, text: str, source: str = "shell") -> Plan:
        intent = self.resolve(text, source=source)
        builder = getattr(self, f"_plan_{_snake(intent.name)}")
        built = builder(intent)
        steps, reasoning = built[0], built[1]
        extras = built[2] if len(built) > 2 else {}
        return Plan(
            id=_plan_id(intent),
            intent=intent,
            steps=steps,
            reasoning=reasoning,
            **extras,
        )

    def _plan_deploy_project(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        risk = RiskLevel.HIGH if env == "production" else RiskLevel.MEDIUM
        reasoning = [
            f"Project identified: {self._config.project_name}",
            f"Environment identified: {env}",
            f"Deploying to {env} is a "
            + ("production modification (HIGH)" if risk is RiskLevel.HIGH else "reversible modification (MEDIUM)"),
            "The Deployment capability performs the deployment; Baygon never deploys directly",
        ]
        steps = [
            Step(id="1", capability="repository", action="get_latest_commit",
                 parameters={}, risk=RiskLevel.LOW),
            Step(id="2", capability="deployment", action="deploy",
                 parameters={"environment": env}, depends_on=["1"], risk=risk),
        ]
        if self._registry.is_available("notification"):
            reasoning.append("Notification capability available: a success notification is planned")
            steps.append(
                Step(id="3", capability="notification", action="notify",
                     parameters={"message": f"Deployment of {self._config.project_name} to {env} finished"},
                     depends_on=["2"], risk=RiskLevel.LOW)
            )
        return steps, reasoning

    def _plan_rollback_deployment(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        risk = RiskLevel.HIGH if env == "production" else RiskLevel.MEDIUM
        return (
            [Step(id="1", capability="deployment", action="rollback",
                  parameters={"environment": env}, risk=risk)],
            [f"Rollback requested on environment {env}",
             "Rollback modifies a deployed environment, validation applies to production"],
        )

    def _plan_open_console(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="ssh", action="command",
                  parameters={"environment": env}, risk=RiskLevel.LOW)],
            [f"Remote access to {env}: Baygon returns the authorized connection "
             "command, it never opens the session itself (EF-010)",
             "The operation is gated by the 'ssh' permission"],
        )

    def _plan_show_database(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="database", action="info",
                  parameters={"environment": env}, risk=RiskLevel.LOW)],
            [f"Database connection information for {env}; secrets are never exposed",
             "The operation is gated by the 'database' permission"],
        )

    def _plan_show_storage(self, intent: Intent) -> tuple[list[Step], list[str]]:
        return (
            [Step(id="1", capability="storage", action="list",
                  parameters={"prefix": ""}, risk=RiskLevel.LOW)],
            ["Listing stored files is a read-only action"],
        )

    def _plan_show_logs(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        since = intent.parameters.get("since_hours", 1)
        return (
            [Step(id="1", capability="logs", action="fetch",
                  parameters={"environment": env, "since_hours": since}, risk=RiskLevel.LOW)],
            [f"Log consultation on {env} over the last {since}h is a read-only action"],
        )

    def _plan_show_metrics(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="metrics", action="fetch",
                  parameters={"environment": env}, risk=RiskLevel.LOW)],
            [f"Metrics consultation on {env} is a read-only action"],
        )

    def _plan_show_status(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="deployment", action="status",
                  parameters={"environment": env}, risk=RiskLevel.LOW)],
            [f"Deployment status of {env} is a read-only action"],
        )

    def _plan_show_history(self, intent: Intent) -> tuple[list[Step], list[str]]:
        return (
            [Step(id="1", capability="repository", action="history",
                  parameters={"limit": 10}, risk=RiskLevel.LOW)],
            ["Repository history is a read-only action"],
        )

    def _plan_propose_changes(self, intent: Intent) -> tuple[list[Step], list[str]]:
        description = intent.raw_input
        return (
            [Step(id="1", capability="review", action="publish",
                  parameters={"title": _title_from(description),
                              "body": f"Proposé par Baygon depuis l'intention : {description}"},
                  risk=RiskLevel.HIGH)],
            ["Publishing pushes a branch and opens a review request: the change "
             "leaves the machine, so explicit validation is required (Article 9)",
             "The operation is gated by the 'publish' permission"],
        )

    def _plan_fix_bug(self, intent: Intent):
        env = intent.parameters["environment"]
        description = intent.raw_input
        reasoning = [
            "The coding agent (developer capability) produces the fix; Baygon never edits code itself",
            "Code changes are reversible through version control (MEDIUM)",
        ]
        steps = [
            Step(id="1", capability="developer", action="fix",
                 parameters={"description": description}, risk=RiskLevel.MEDIUM),
        ]
        test_command = self._config.commands.get("test")
        if test_command is None:
            reasoning.append(
                "No declared 'test' command in baygon.yaml: the fix cannot be "
                "independently verified, single attempt only"
            )
            return steps, reasoning

        reasoning.append(
            "Independent QA: Baygon runs the declared 'test' command to validate the fix; "
            "on failure the QA report is fed back to the agent (bounded rounds)"
        )
        steps.append(
            Step(id="2", capability="workspace", action="execute",
                 parameters={"command": "test", "command_line": str(test_command),
                             "environment": env},
                 depends_on=["1"], risk=RiskLevel.MEDIUM)
        )
        message = f"Bug résolu et validé par Baygon — {description}"
        last_step = "2"
        if self._registry.is_available("review"):
            reasoning.append(
                "Review capability available: the validated fix is published for human "
                "review, which makes the plan sensitive (explicit validation required)"
            )
            steps.append(
                Step(id="3", capability="review", action="publish",
                     parameters={"title": _title_from(description),
                                 "body": "Correction produite par l'agent et validée "
                                         "par la commande de test déclarée."},
                     depends_on=["2"], risk=RiskLevel.HIGH)
            )
            last_step = "3"
            message += "\n{{3.url}}"  # resolved from the publication result
        if self._registry.is_available("notification"):
            steps.append(
                Step(id=str(int(last_step) + 1), capability="notification", action="notify",
                     parameters={"message": message},
                     depends_on=[last_step], risk=RiskLevel.LOW)
            )
        return steps, reasoning, {"max_rounds": 3, "feedback_step": "1"}

    def _plan_run_command(self, intent: Intent) -> tuple[list[Step], list[str]]:
        command = intent.parameters["command"]
        command_line = str(self._config.commands[command])
        env = intent.parameters["environment"]
        risk = RiskLevel.HIGH if env == "production" else RiskLevel.MEDIUM
        reasoning = [
            f"Command {command!r} is declared in baygon.yaml; the core does not code it",
            f"It runs on {env} through the Workspace capability",
        ]
        if risk is RiskLevel.HIGH:
            reasoning.append("Running a command on production is a production modification (HIGH)")
        steps = [
            Step(id="1", capability="workspace", action="execute",
                 parameters={"command": command, "command_line": command_line, "environment": env},
                 risk=risk),
        ]
        return steps, reasoning

    def _plan_backup_project(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="backup", action="backup",
                  parameters={"environment": env}, risk=RiskLevel.MEDIUM)],
            [f"Backup of {env} is an additive, reversible operation (MEDIUM)"],
        )

    def _plan_restore_project(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        return (
            [Step(id="1", capability="recovery", action="restore",
                  parameters={"environment": env}, risk=RiskLevel.CRITICAL)],
            [f"Restoring {env} overwrites its current state: destructive action (CRITICAL)",
             "The plan stays suspended until explicit validation"],
        )

    def _plan_diagnose(self, intent: Intent) -> tuple[list[Step], list[str]]:
        env = intent.parameters["environment"]
        since = intent.parameters.get("since_hours", 24)
        reasoning = [
            f"Diagnosis on {env}: gather logs, metrics and last deployment status",
            "All collection steps are read-only and independent, they may run in parallel",
        ]
        steps = [
            Step(id="1", capability="logs", action="fetch",
                 parameters={"environment": env, "since_hours": since}, risk=RiskLevel.LOW),
            Step(id="2", capability="metrics", action="fetch",
                 parameters={"environment": env}, risk=RiskLevel.LOW),
            Step(id="3", capability="deployment", action="status",
                 parameters={"environment": env}, risk=RiskLevel.LOW),
        ]
        if self._registry.is_available("ai"):
            reasoning.append(
                "AI capability available: the gathered context is sent to the model for analysis"
            )
            steps.append(
                Step(id="4", capability="ai", action="complete",
                     parameters={"prompt": f"Diagnose the state of {self._config.project_name} on {env}"},
                     depends_on=["1", "2", "3"], risk=RiskLevel.LOW)
            )
        else:
            reasoning.append("No AI capability available: raw context is returned (degraded mode)")
        return steps, reasoning


def _title_from(description: str) -> str:
    """First line of the intention, trimmed, as a review request title."""
    return description.strip().splitlines()[0][:72] if description.strip() else "Baygon"


def _snake(name: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _plan_id(intent: Intent) -> str:
    """Deterministic plan identifier: identical context -> identical id."""
    digest = hashlib.sha256(
        f"{intent.name}|{sorted(intent.parameters.items())}|{intent.raw_input}".encode()
    ).hexdigest()
    return f"plan-{digest[:12]}"
