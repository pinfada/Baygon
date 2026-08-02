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

from baygon import __version__
from baygon.core.errors import BaygonError, ValidationRequiredError
from baygon.core.kernel import Kernel


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

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
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


def _dispatch(kernel: Kernel, args: argparse.Namespace) -> int:
    if args.command == "validate":
        print(f"ok: {kernel.config.path} is valid (project {kernel.config.project_name!r})")
        return 0

    if args.command == "capabilities":
        print(json.dumps(kernel.capabilities(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "models":
        for entry in kernel.models():
            freshness = {True: "à jour", False: "OBSOLÈTE", None: "inconnu"}[entry["up_to_date"]]
            model = entry.get("model") or "—"
            print(f"{entry['name']:<20} {model:<24} {entry['adapter']:<20} "
                  f"{entry['state']:<8} {freshness}")
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
        result = kernel.execute(plan, approved=args.yes)
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False, default=str))
        return 0 if result.success else 1

    if args.command == "resume":
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
