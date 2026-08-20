"""Command-line entry point for orchestration smoke scenarios."""

import argparse
import sys

from dotenv import load_dotenv

from .reporting import render_human, render_json
from .html_output import (
    HtmlOutputError,
    validate_html_output_directory,
    write_smoke_html,
)
from .scenarios import SCENARIOS, run_scenario


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Run offline-first orchestration smoke scenarios"
    )
    result.add_argument("scenario", nargs="?", choices=sorted(SCENARIOS))
    result.add_argument("--list", action="store_true", help="list available scenarios")
    result.add_argument(
        "--json", action="store_true", help="emit provider-neutral JSON"
    )
    result.add_argument(
        "--live",
        action="store_true",
        help="explicitly allow registered provider network execution",
    )
    result.add_argument(
        "--target",
        action="append",
        dest="targets",
        help="override target ID (repeat for a batch)",
    )
    result.add_argument(
        "--html-dir",
        metavar="PATH",
        help="write separate Portfolio views and a linked index to PATH",
    )
    return result


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    if args.list:
        if args.scenario or args.live or args.json or args.targets or args.html_dir:
            parser().error("--list cannot be combined with scenario options")
        print("\n".join(sorted(SCENARIOS)))
        return 0
    if not args.scenario:
        parser().error("a scenario is required unless --list is used")
    if args.targets and not args.live:
        parser().error(
            "--target requires --live because fixture scenarios use fixed payload identifiers"
        )
    if args.scenario == "partial-failure" and args.live:
        parser().error("partial-failure is fixture-only and cannot be used with --live")
    if args.html_dir:
        try:
            validate_html_output_directory(args.html_dir)
        except HtmlOutputError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2

    if args.live:
        # python-dotenv preserves credentials already exported by the caller.
        load_dotenv(override=False)
    result = run_scenario(
        args.scenario,
        live=args.live,
        targets=tuple(args.targets) if args.targets else None,
    )
    index = None
    if args.html_dir:
        try:
            index = write_smoke_html(result, args.html_dir)
        except HtmlOutputError as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
    print(render_json(result) if args.json else render_human(result))
    if index is not None:
        notice = f"HTML index: {index}"
        print(notice, file=sys.stderr if args.json else sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
