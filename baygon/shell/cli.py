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
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("validate", help="validate baygon.yaml")
    sub.add_parser("capabilities", help="list available capabilities and implementations")
    sub.add_parser("context", help="show the project context built by the Context Engine")

    serve = sub.add_parser("serve", help="expose the Shell as a REST API")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)

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

    history = sub.add_parser("history", help="show executed intentions")
    history.add_argument("--limit", type=int, default=20)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        kernel = Kernel.start(args.file)
    except BaygonError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for name, error in kernel.plugins.failures.items():
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


def _dispatch(kernel: Kernel, args: argparse.Namespace) -> int:
    if args.command == "validate":
        print(f"ok: {kernel.config.path} is valid (project {kernel.config.project_name!r})")
        return 0

    if args.command == "capabilities":
        print(json.dumps(kernel.capabilities(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "context":
        print(json.dumps(kernel.context(), indent=2, ensure_ascii=False))
        return 0

    if args.command == "serve":
        from baygon.shell.api import serve

        serve(kernel, host=args.host, port=args.port)
        return 0

    if args.command in ("plan", "explain"):
        plan = kernel.plan(args.intent)
        print(plan.explain())
        return 0

    if args.command == "run":
        plan = kernel.plan(args.intent)
        if plan.requires_validation and not args.yes:
            print(plan.explain())
            print("\nThis plan contains sensitive actions.", file=sys.stderr)
            print("Re-run with --yes to approve it.", file=sys.stderr)
            return 3
        result = kernel.execute(plan, approved=args.yes)
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
