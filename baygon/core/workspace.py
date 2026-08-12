"""Workspace — one command, a fleet of projects.

Baygon was born repo by repo: one baygon.yaml, one kernel, one journal.
The operator's real question is wider — « est-ce que nous avons des
incidents ? » across everything they run. The workspace adds exactly
two things on top of the existing kernels: the fan-out (ask every
project in parallel) and the synthesis (answer like a briefing, not
like a log).

What it deliberately does NOT add is shared context. Each project
keeps its own kernel, providers, journal and permissions — isolation
is not an option, it is the construction. A model asked about one
project never sees another project's logs or code.

The safety contract stays opt-in: `policy.autonomous` (approve
sensitive plans) and `policy.self_heal` (a failed run triggers
« corrige le dernier incident ») are declared in the workspace file by
its sole operator, never assumed (Article 7). Healing reuses the
existing bounded Dev → QA loop unchanged: same rounds, same QA gate.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from baygon.capabilities.base import AICapability
from baygon.core.errors import BaygonError, ConfigError, ValidationRequiredError
from baygon.core.kernel import Kernel
from baygon.core.plugins import _load_class

WORKSPACE_FILE = "baygon-workspace.yaml"
SUPPORTED_VERSIONS = (1,)
KNOWN_SECTIONS = ("version", "workspace", "projects", "policy", "orchestrator")
KNOWN_POLICIES = ("autonomous", "self_heal")

#: Projects inspected at once. Each holds its own kernel and providers;
#: the bound protects the operator's machine, not any shared state.
MAX_PARALLEL_PROJECTS = 8

#: What a failed self-healing means for the operator, spelled out.
INTERVENTION = "Intervention requise."


@dataclass(frozen=True)
class WorkspacePolicy:
    """What the sole operator has explicitly delegated. Defaults: nothing."""

    autonomous: bool = False
    self_heal: bool = False


@dataclass(frozen=True)
class WorkspaceConfig:
    version: int
    name: str
    projects: dict[str, Path]
    policy: WorkspacePolicy
    orchestrator: dict[str, Any] | None
    path: Path


@dataclass
class ProjectOutcome:
    """What happened on one project, reduced to what the report needs."""

    name: str
    status: str  # ok | healed | heal_failed | failed | needs_validation
    cause: str | None = None       # origin of the incident, if any
    heal_cause: str | None = None  # why the self-healing failed, if it did
    rounds: int = 0                # Dev → QA rounds the healing used
    duration_ms: float = 0.0

    def to_fact(self) -> dict[str, Any]:
        return {
            "projet": self.name,
            "statut": self.status,
            "incident": self.cause,
            "echec_correction": self.heal_cause,
            "rondes_de_correction": self.rounds,
            "duree_ms": round(self.duration_ms),
        }


def load_workspace(path: str | Path) -> WorkspaceConfig:
    """Load and validate a ``baygon-workspace.yaml`` file.

    Same contract as a project file: strict, or nothing. A typo'd
    policy key silently defaulting to False would be exactly the kind
    of quiet failure this refuses.
    """
    file = Path(path)
    if file.is_dir():
        file = file / WORKSPACE_FILE
    if not file.exists():
        raise ConfigError(f"Workspace file not found: {file}")
    try:
        raw = yaml.safe_load(file.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {file}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{file} must contain a YAML mapping")

    unknown = set(raw) - set(KNOWN_SECTIONS)
    if unknown:
        raise ConfigError(f"Unknown top-level section(s): {', '.join(sorted(unknown))}")
    version = raw.get("version")
    if version not in SUPPORTED_VERSIONS:
        raise ConfigError(
            f"Unsupported workspace version {version!r}; "
            f"supported: {', '.join(map(str, SUPPORTED_VERSIONS))}"
        )

    meta = raw.get("workspace") or {}
    if not isinstance(meta, dict):
        raise ConfigError("Section 'workspace' must be a mapping")

    entries = raw.get("projects")
    if not isinstance(entries, dict) or not entries:
        raise ConfigError(
            "A workspace must declare at least one project under 'projects'"
        )
    projects: dict[str, Path] = {}
    resolved_names: dict[Path, str] = {}
    for name, entry in entries.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            raise ConfigError(f"Project {name!r} must declare a 'path'")
        declared = Path(entry["path"])
        path = declared if declared.is_absolute() else file.parent / declared
        # Two aliases of one directory would run two kernels on the same
        # journal and the same working tree — concurrently, under the
        # fan-out. Isolation is the construction; aliases would break it.
        twin = resolved_names.get(path.resolve())
        if twin is not None:
            raise ConfigError(
                f"Projects {twin!r} and {name!r} point to the same directory "
                f"({path.resolve()})"
            )
        resolved_names[path.resolve()] = str(name)
        projects[str(name)] = path

    policy_raw = raw.get("policy") or {}
    if not isinstance(policy_raw, dict):
        raise ConfigError("Section 'policy' must be a mapping")
    unknown = set(policy_raw) - set(KNOWN_POLICIES)
    if unknown:
        raise ConfigError(
            f"Unknown policy key(s): {', '.join(sorted(unknown))}; "
            f"known: {', '.join(KNOWN_POLICIES)}"
        )
    policy = WorkspacePolicy(
        autonomous=bool(policy_raw.get("autonomous", False)),
        self_heal=bool(policy_raw.get("self_heal", False)),
    )

    orchestrator = raw.get("orchestrator")
    if orchestrator is not None:
        if not isinstance(orchestrator, dict) or not isinstance(
            orchestrator.get("plugin"), str
        ):
            raise ConfigError("Section 'orchestrator' must declare a 'plugin'")

    return WorkspaceConfig(
        version=int(version),
        name=str(meta.get("name", "workspace")),
        projects=projects,
        policy=policy,
        orchestrator=orchestrator,
        path=file,
    )


@dataclass
class WorkspaceReport:
    """The executive answer: what happened, project by project."""

    workspace: str
    question: str
    outcomes: dict[str, ProjectOutcome]
    unavailable: dict[str, str] = field(default_factory=dict)

    @property
    def global_status(self) -> str:
        """ok (all green), healed (incidents fixed), attention (you)."""
        statuses = {outcome.status for outcome in self.outcomes.values()}
        if (
            self.unavailable
            or statuses & {"heal_failed", "failed", "needs_validation"}
        ):
            return "attention"
        if "healed" in statuses:
            return "healed"
        return "ok"

    def facts(self) -> dict[str, Any]:
        """The report's raw material — everything the journal knows,
        nothing it does not. An orchestrator model narrates from this
        and only this: no fact here, no claim in the report."""
        return {
            "workspace": self.workspace,
            "question": self.question,
            "statut_global": self.global_status,
            "projets": [o.to_fact() for o in self.outcomes.values()],
            "projets_indisponibles": dict(self.unavailable),
        }

    def render(self) -> str:
        """Deterministic briefing — the guaranteed floor (EF-014).

        A declared orchestrator model writes better prose on top of the
        same facts; this rendering is what its absence degrades to.
        """
        healthy = [n for n, o in self.outcomes.items() if o.status == "ok"]
        lines = [_RULE, f"STATUT GLOBAL : {self._headline()}", _RULE, ""]
        for name, outcome in self.outcomes.items():
            if outcome.status != "ok":
                lines += self._block(name, outcome) + [""]
        for name, error in self.unavailable.items():
            lines += [f"[{name}]", f"• Projet indisponible : {error}", ""]
        if healthy:
            label = "Aucun incident à signaler."
            lines += [f"[{', '.join(healthy)}]", f"🟢 {label}", ""]
        return "\n".join(lines).rstrip() + "\n"

    def _headline(self) -> str:
        total = len(self.outcomes) + len(self.unavailable)
        if self.global_status == "ok":
            return f"🟢 Tous les systèmes sont opérationnels ({total} projets)"
        if self.global_status == "healed":
            healed = sum(1 for o in self.outcomes.values() if o.status == "healed")
            plural = "s" if healed > 1 else ""
            return (f"🟠 {healed} incident{plural} détecté{plural} "
                    f"et corrigé{plural} automatiquement")
        return "🔴 Intervention requise"

    def _block(self, name: str, outcome: ProjectOutcome) -> list[str]:
        seconds = f"{outcome.duration_ms / 1000:.1f}".replace(".", ",")
        if outcome.status == "healed":
            plural = "s" if outcome.rounds > 1 else ""
            return [
                f"[{name}]",
                f"• Incident : « {self.question} » a échoué — {outcome.cause}",
                f"• Action   : correctif appliqué par l'agent de code "
                f"({outcome.rounds} ronde{plural}), QA repassée au vert",
                f"• Impact   : incident détecté et corrigé automatiquement en {seconds} s",
            ]
        if outcome.status == "heal_failed":
            return [
                f"[{name}]",
                f"• Incident : « {self.question} » a échoué — {outcome.cause}",
                f"• Auto-correction échouée après {outcome.rounds} rondes — "
                f"{outcome.heal_cause}",
                f"• {INTERVENTION}",
            ]
        if outcome.status == "needs_validation":
            return [
                f"[{name}]",
                f"• En attente : {outcome.cause}",
            ]
        return [
            f"[{name}]",
            f"• Échec : {outcome.cause}",
            f"• {INTERVENTION}",
        ]


_RULE = "-" * 70


def _matching(entries: list[dict[str, Any]], plan_id: str) -> int:
    """Journal entries recorded under this plan id."""
    return sum(
        1 for entry in entries if (entry.get("plan") or {}).get("id") == plan_id
    )


#: The meta-agent's own instructions. It synthesizes; it never plans,
#: never executes, never invents a number the facts do not carry.
_ORCHESTRATOR_PROMPT = """\
Tu es l'orchestrateur d'un parc de projets logiciels. Des agents experts,
un par projet, viennent de répondre chacun sur leur propre périmètre.
Rédige la synthèse décisionnelle de leurs résultats pour l'opérateur :

- Une ligne « STATUT GLOBAL » d'abord (🟢 opérationnel, 🟠 incident corrigé
  automatiquement, 🔴 intervention requise).
- Puis un bloc par projet touché : l'incident en termes métier, l'origine,
  l'action réalisée, l'impact, et l'état des vérifications (QA).
- Regroupe les projets sans incident en une ligne.
- Aucune stacktrace, aucun JSON, aucun jargon d'exécution.
- N'invente jamais un chiffre ou un fait absent des données.

Les faits, et rien d'autre :
{facts}
"""


class Workspace:
    """The fleet: one kernel per project, one report for the operator."""

    def __init__(self, config: WorkspaceConfig) -> None:
        self.config = config
        self.failures: dict[str, str] = {}
        #: The narrator is a comfort, not a project: its failure is kept
        #: apart so it can never paint a healthy fleet as broken.
        self.orchestrator_error: str | None = None
        self._kernels: dict[str, Kernel] = {}
        self._orchestrator: AICapability | None = None
        for name, path in config.projects.items():
            try:
                self._kernels[name] = Kernel.start(path)
            except BaygonError as exc:
                # Isolate the broken project; the others keep working.
                self.failures[name] = str(exc)
        if config.orchestrator is not None:
            try:
                cls = _load_class(config.orchestrator["plugin"])
                if not issubclass(cls, AICapability):
                    raise BaygonError(
                        f"orchestrator plugin {config.orchestrator['plugin']!r} "
                        "must provide the 'ai' capability"
                    )
                self._orchestrator = cls(config.orchestrator.get("options") or {})
            except Exception as exc:
                self.orchestrator_error = str(exc)

    @classmethod
    def start(cls, path: str | Path) -> "Workspace":
        return cls(load_workspace(path))

    def projects(self) -> list[str]:
        return sorted(self._kernels)

    def kernel(self, name: str) -> Kernel:
        return self._kernels[name]

    def run(
        self,
        text: str,
        approved: bool = False,
        ai: bool = True,
        ai_model: str | None = None,
        on_progress: Callable[[str], None] | None = None,
    ) -> WorkspaceReport:
        """Ask every project, in parallel, each in its own context."""
        progress = on_progress or (lambda message: None)
        approved = approved or self.config.policy.autonomous
        progress(f"Inspection de {len(self._kernels)} projet(s) du workspace…")
        outcomes: dict[str, ProjectOutcome] = {}
        if self._kernels:
            workers = min(len(self._kernels), MAX_PARALLEL_PROJECTS)
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    name: pool.submit(
                        self._run_one, name, kernel, text, approved,
                        ai, ai_model, progress,
                    )
                    for name, kernel in sorted(self._kernels.items())
                }
                outcomes = {name: future.result() for name, future in futures.items()}
        return WorkspaceReport(
            workspace=self.config.name,
            question=text,
            outcomes=outcomes,
            unavailable=dict(self.failures),
        )

    def narrate(self, report: WorkspaceReport) -> str:
        """The report, written by the orchestrator model when one is
        declared — from the journal's facts and nothing else. Without a
        model, or when it fails, the deterministic rendering answers:
        degraded, never broken (EF-014)."""
        if self._orchestrator is None:
            return report.render()
        facts = json.dumps(report.facts(), ensure_ascii=False, indent=2)
        try:
            told = self._orchestrator.complete(
                _ORCHESTRATOR_PROMPT.format(facts=facts)
            )
        except Exception:
            return report.render()
        return told if told and told.strip() else report.render()

    def _run_one(
        self,
        name: str,
        kernel: Kernel,
        text: str,
        approved: bool,
        ai: bool,
        ai_model: str | None,
        progress: Callable[[str], None],
    ) -> ProjectOutcome:
        try:
            plan = kernel.plan(text, ai=ai, ai_model=ai_model)
            if plan.requires_validation and not approved:
                return ProjectOutcome(
                    name, "needs_validation",
                    cause="ce plan contient des actions sensibles — relancez "
                          "avec --yes, ou déclarez policy.autonomous dans le "
                          "workspace",
                )
            result = kernel.execute(plan, approved=approved)
        except ValidationRequiredError as exc:
            return ProjectOutcome(name, "needs_validation", cause=str(exc))
        except Exception as exc:
            # Isolation holds for programming errors too, not only for
            # well-mannered BaygonErrors: one project's crash is its
            # outcome, never the fleet's.
            return ProjectOutcome(name, "failed", cause=str(exc))
        if result.success:
            return ProjectOutcome(name, "ok", duration_ms=result.duration_ms)
        cause = str((result.failure or {}).get("cause", "cause inconnue"))
        if not (self.config.policy.self_heal and approved):
            # Self-healing fixes code and runs commands: opt-in, never
            # a default (Article 7).
            return ProjectOutcome(
                name, "failed", cause=cause, duration_ms=result.duration_ms
            )
        progress(f"Auto-correction en cours sur [{name}]…")
        return self._heal(name, kernel, cause, result.duration_ms)

    def _heal(
        self, name: str, kernel: Kernel, cause: str, elapsed_ms: float
    ) -> ProjectOutcome:
        """Hand the journaled incident to the existing Dev → QA loop."""
        before = kernel.audit.entries(limit=1000)
        try:
            heal = kernel.run("corrige le dernier incident", approved=True)
        except Exception as exc:
            return ProjectOutcome(
                name, "heal_failed", cause=cause, heal_cause=str(exc),
                duration_ms=elapsed_ms,
            )
        # The Dev → QA loop journals every round under the same plan id;
        # the returned result only carries the last one. And plan ids are
        # content-derived: every healing of this project shares one id,
        # so earlier healings are subtracted out — this report counts the
        # rounds of THIS healing only.
        rounds = max(
            1,
            _matching(kernel.audit.entries(limit=1000), heal.plan.id)
            - _matching(before, heal.plan.id),
        )
        duration = elapsed_ms + heal.duration_ms
        if heal.success:
            return ProjectOutcome(
                name, "healed", cause=cause, rounds=rounds, duration_ms=duration
            )
        return ProjectOutcome(
            name, "heal_failed", cause=cause,
            heal_cause=str((heal.failure or {}).get("cause", "cause inconnue")),
            rounds=rounds, duration_ms=duration,
        )
