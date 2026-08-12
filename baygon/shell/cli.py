"""Baygon Shell (terminal interface).

The Shell is the single entry point. It receives user intentions and
delegates everything to the core. It contains no business logic, so any
other interface (API, web, mobile, voice) can be added without touching
the core.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import TextIO

from baygon import __version__
from baygon.core import events
from baygon.core.errors import BaygonError, ValidationRequiredError
from baygon.core.kernel import Kernel


def attach_progress(kernel: Kernel, stream: TextIO) -> None:
    """Report execution progress on `stream` as the plan runs (EF-020).

    A command that calls an AI model can take seconds; going silent
    until the answer is ready looks like a freeze. Progress is written
    on the error stream so standard output keeps carrying nothing but
    the machine-readable result.

    The reporter only listens: a stream that cannot be written to
    (closed pipe, full disk) must never take the execution down with it.
    """
    state = {"total": 0, "done": 0}

    def write(line: str) -> None:
        try:
            stream.write(line)
            stream.flush()
        except Exception:
            # Progress is a courtesy, never a dependency.
            return

    def started(event: events.Event) -> None:
        state["total"] = int(event.payload.get("steps", 0))
        state["done"] = 0

    def step_started(event: events.Event) -> None:
        position = f"{state['done'] + 1}/{state['total']}" if state["total"] else "…"
        write(f"  [{position}] {_label(event)} …\n")

    def step_finished(event: events.Event) -> None:
        state["done"] += 1
        payload = event.payload
        if payload.get("reused"):
            outcome = "reused"
        else:
            outcome = "ok" if payload.get("success") else "failed"
        duration = payload.get("duration_ms")
        timing = f" ({duration:.0f} ms)" if isinstance(duration, (int, float)) else ""
        position = f"{state['done']}/{state['total']}" if state["total"] else "…"
        write(f"  [{position}] {_label(event)} {outcome}{timing}\n")

    kernel.bus.subscribe(events.EXECUTION_STARTED, started)
    kernel.bus.subscribe(events.STEP_STARTED, step_started)
    kernel.bus.subscribe(events.STEP_FINISHED, step_finished)


def _label(event: events.Event) -> str:
    payload = event.payload
    return f"{payload.get('capability', '?')}.{payload.get('action', '?')}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="baygon",
        description="Baygon — one intention, one answer, from anywhere.",
    )
    parser.add_argument("--version", action="version", version=f"baygon {__version__}")
    parser.add_argument(
        "-f", "--file", default="baygon.yaml",
        help="path to baygon.yaml (default: ./baygon.yaml)",
    )
    parser.add_argument(
        "--projects", metavar="DIR", default=None,
        help="manage several projects: discover every baygon.yaml under DIR",
    )
    parser.add_argument(
        "--project", metavar="NAME", default=None,
        help="target project when several are managed (default: named in the intention)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    parser.add_argument(
        "--no-ai", action="store_true",
        help="deterministic rules only: never call an AI model (EF-014)",
    )
    parser.add_argument(
        "--model", metavar="NAME", default=None,
        help="use this declared AI model (see `baygon models`)",
    )
    sub.add_parser("projects", help="list the managed projects")
    sub.add_parser("models", help="list the AI models this session may choose")
    sub.add_parser("validate", help="validate baygon.yaml")
    sub.add_parser("capabilities", help="list available capabilities and implementations")
    sub.add_parser("context", help="show the project context built by the Context Engine")
    doctor = sub.add_parser(
        "doctor", help="what can be done on this project, and what is missing"
    )
    doctor.add_argument("--json", action="store_true", help="machine-readable output")

    serve = sub.add_parser("serve", help="expose the Shell as a REST API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument(
        "--insecure", action="store_true",
        help="explicitly start without authentication (local development only)",
    )
    serve.add_argument(
        "--rate-limit", type=int, default=120, metavar="N",
        help="max requests per minute per client (default 120; 0 disables)",
    )

    plan = sub.add_parser("plan", help="build and explain the plan for an intention")
    plan.add_argument("intent", help="intention in natural language, e.g. 'deploy to staging'")

    run = sub.add_parser("run", help="build then execute the plan for an intention")
    run.add_argument("intent", help="intention in natural language")
    run.add_argument(
        "--yes", action="store_true",
        help="approve sensitive actions (production, destructive)",
    )

    explain = sub.add_parser("explain", help="explain why: reasoning behind a plan")
    explain.add_argument("intent", help="intention in natural language")

    resume = sub.add_parser("resume", help="resume the last failed execution")
    resume.add_argument("--plan", default=None, help="plan id to resume (default: last failure)")
    resume.add_argument("--yes", action="store_true", help="approve sensitive actions")

    history = sub.add_parser("history", help="show executed intentions")
    history.add_argument("--limit", type=int, default=20)

    workspace = sub.add_parser(
        "workspace", help="pilot a fleet of projects from one file"
    )
    workspace.add_argument(
        "-w", "--workspace-file", default="baygon-workspace.yaml",
        dest="workspace_file",
        help="path to baygon-workspace.yaml (default: ./baygon-workspace.yaml)",
    )
    wsub = workspace.add_subparsers(dest="workspace_command", required=True)
    wsub.add_parser("projects", help="list the workspace's projects")
    wsub.add_parser("validate", help="validate baygon-workspace.yaml")
    wrun = wsub.add_parser(
        "run", help="ask every project, get one executive report"
    )
    wrun.add_argument("intent", help="intention in natural language")
    wrun.add_argument(
        "--yes", action="store_true",
        help="approve sensitive actions on every project for this run",
    )
    wrun.add_argument(
        "--json", action="store_true",
        help="machine-readable facts instead of the briefing",
    )

    return parser


def _tolerate_narrow_encodings() -> None:
    """Never let the console encoding take a command down (EF-020).

    Windows consoles often default to a legacy code page (cp1252) that
    cannot encode the ✓/✗/… glyphs the reports use. The answer matters
    more than the glyph: degrade the character, never the command.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except Exception:
                pass


def _workspace_main(args: argparse.Namespace) -> int:
    """The fleet commands: quiet pipeline, executive report.

    Progress is one line per event on the error stream — never the
    step-by-step feed of a single project. Standard output carries the
    briefing (or the raw facts with --json), nothing else.
    """
    import json as _json

    from baygon.core.workspace import Workspace

    workspace = Workspace.start(args.workspace_file)
    if args.workspace_command == "projects":
        for name in workspace.projects():
            print(name)
        return 0
    if args.workspace_command == "validate":
        config = workspace.config
        print(f"ok: {config.path} is valid "
              f"(workspace {config.name!r}, {len(config.projects)} projet(s))")
        for name, error in workspace.failures.items():
            print(f"warning: {name!r} unavailable: {error}", file=sys.stderr)
        return 0

    def progress(message: str) -> None:
        if sys.stderr.isatty():
            print(message, file=sys.stderr)

    report = workspace.run(args.intent, approved=args.yes, on_progress=progress)
    if args.json:
        print(_json.dumps(report.facts(), indent=2, ensure_ascii=False))
    else:
        print(workspace.narrate(report))
    return 1 if report.global_status == "attention" else 0


def main(argv: list[str] | None = None) -> int:
    _tolerate_narrow_encodings()
    args = _build_parser().parse_args(argv)
    if args.command == "workspace":
        try:
            return _workspace_main(args)
        except BaygonError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    try:
        kernel = _select_kernel(args)
        if kernel is None:  # the `projects` listing already printed
            return 0
    except BaygonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    failures = getattr(getattr(kernel, "plugins", None), "failures", {})
    for name, error in failures.items():
        print(f"warning: provider {name!r} unavailable: {error}", file=sys.stderr)

    try:
        return _dispatch(kernel, args)
    except ValidationRequiredError as exc:
        print(f"suspended: {exc}", file=sys.stderr)
        print("re-run with --yes to approve this plan", file=sys.stderr)
        return 3
    except BaygonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _select_target(args: argparse.Namespace):
    """Return the project router: one project, or several."""
    from baygon.core.projects import ProjectManager, SingleProject

    if args.projects is None:
        return SingleProject(Kernel.start(args.file))
    manager = ProjectManager.discover(args.projects)
    for name, error in manager.failures.items():
        print(f"warning: project {name!r} unavailable: {error}", file=sys.stderr)
    return manager


def _select_kernel(args: argparse.Namespace) -> Kernel | None:
    """Kernel addressed by this command, or None once handled here."""
    target = _select_target(args)
    if args.command == "projects":
        for name in target.projects():
            print(name)
        return None
    if args.command == "serve":
        # The server routes per request: no project to resolve now.
        return target
    intent_text = getattr(args, "intent", "") or ""
    return target.resolve(intent_text, explicit=args.project)


def _print_readiness(report: dict) -> None:
    """The answer to "what works here?", readable at a glance."""
    print(f"{report['project']} — {report['ready_count']}/{report['total_count']} "
          "intentions utilisables")

    ready = [entry["intent"] for entry in report["intents"] if entry["ready"]]
    if ready:
        print("\nUtilisables :")
        for name in ready:
            print(f"  ✓ {name}")
    if report["commands"]:
        print(f"  ✓ commandes déclarées, par leur nom : {', '.join(report['commands'])}")

    blocked = [entry for entry in report["intents"] if not entry["ready"]]
    if blocked:
        print("\nIndisponibles :")
        for entry in blocked:
            reason = []
            if entry["missing_capabilities"]:
                reason.append("capacité non déclarée : " + ", ".join(entry["missing_capabilities"]))
            if entry["missing_permissions"]:
                reason.append("permission refusée : " + ", ".join(entry["missing_permissions"]))
            print(f"  ✗ {entry['intent']:<20} {' ; '.join(reason)}")

    failed = [p for p in report["providers"] if p["state"] != "ACTIVE"]
    if failed or report["failures"]:
        print("\nFournisseurs en difficulté :")
        for provider in failed:
            print(f"  ! {provider['name']:<20} {provider['capability']:<12} {provider['state']}")
        for name, error in report["failures"].items():
            print(f"  ! {name:<20} non chargé : {error}")


def _report_progress(kernel: Kernel) -> None:
    """Show progress on an interactive terminal only.

    Piped or redirected output is being read by a program, not by a
    person waiting: staying silent there keeps the stream clean.
    """
    if sys.stderr.isatty():
        attach_progress(kernel, sys.stderr)


def _dispatch(kernel: Kernel, args: argparse.Namespace) -> int:
    if args.command == "validate":
        print(f"ok: {kernel.config.path} is valid (project {kernel.config.project_name!r})")
        return 0

    if args.command == "capabilities":
        print(json.dumps(kernel.capabilities(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "models":
        for entry in kernel.models():
            if entry.get("reachable") is False:
                # Saying "unknown" would send the operator to a model
                # that cannot answer; say it cannot be reached.
                freshness = "INJOIGNABLE"
            else:
                freshness = {True: "à jour", False: "OBSOLÈTE",
                             None: "inconnu"}[entry["up_to_date"]]
            model = entry.get("model") or "—"
            print(f"{entry['name']:<20} {model:<24} {entry['adapter']:<20} "
                  f"{entry['state']:<8} {freshness}")
        return 0

    if args.command == "doctor":
        report = kernel.readiness()
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        _print_readiness(report)
        return 0

    if args.command == "context":
        print(json.dumps(kernel.context(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "serve":
        from baygon.shell.api import TOKEN_ENV_VAR, resolve_api_token, serve

        first = kernel.kernel(kernel.projects()[0])
        token = resolve_api_token(first)
        if token is None and not args.insecure:
            # Security by default (Article 7): no token, no server.
            print(
                f"error: no API token found (set {TOKEN_ENV_VAR} or provide it via the "
                "secrets capability); pass --insecure to explicitly start without "
                "authentication",
                file=sys.stderr,
            )
            return 2
        serve(kernel, host=args.host, port=args.port, token=token,
              rate_limit_per_minute=args.rate_limit or None)
        return 0

    if args.command in ("plan", "explain"):
        plan = kernel.plan(args.intent, ai=not args.no_ai, ai_model=args.model)
        print(plan.explain())
        return 0

    if args.command == "run":
        plan = kernel.plan(args.intent, ai=not args.no_ai, ai_model=args.model)
        if plan.requires_validation and not args.yes:
            print(plan.explain())
            print("\nThis plan contains sensitive actions.", file=sys.stderr)
            print("Re-run with --yes to approve it.", file=sys.stderr)
            return 3
        _report_progress(kernel)
        result = kernel.execute(plan, approved=args.yes)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
        return 0 if result.success else 1

    if args.command == "resume":
        _report_progress(kernel)
        result = kernel.resume(plan_id=args.plan, approved=args.yes)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
        return 0 if result.success else 1

    if args.command == "history":
        for entry in kernel.history(limit=args.limit):
            print(
                f"{entry['date']}  {entry['user']:<12} {entry['intent']:<20} "
                f"{entry['status']:<10} {entry['input']!r}"
            )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
