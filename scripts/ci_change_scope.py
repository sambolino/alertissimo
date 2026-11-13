#!/usr/bin/env python3
"""Classify non-runtime PR changes; manual and uncertain diffs run backend CI."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess

import yaml


CI_FILES = frozenset({
    ".github/workflows/dsl.yml",
    ".github/workflows/semantic-registry.yml",
    ".github/workflows/ui.yml",
    "scripts/ci_change_scope.py",
    "tests/test_ci_change_scope.py",
})
REGULAR_MODES = {"100644", "100755"}


@dataclass(frozen=True)
class Scope:
    run_backend: bool
    reason: str


def git(repo: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), *arguments])


def yaml_tokens(content: bytes) -> tuple:
    """Retain order, duplicates, tags, scalar types/styles and block content.

    Loading into dicts could hide duplicate-key/order changes or equate True and
    1. Parsing/scanning constructs no native objects, including for custom tags.
    Only source marks and comments are ignored.
    """
    if len(content) > 1024 * 1024:
        raise ValueError("YAML exceeds fast-path inspection limit")
    tuple(yaml.parse(content))  # Require a syntactically valid document stream.
    return tuple(
        (type(token).__name__, tuple(
            (name, value) for name, value in vars(token).items()
            if name not in {"start_mark", "end_mark"}
        ))
        for token in yaml.scan(content)
    )


def classify(repo: Path, *, event: str, base: str, head: str = "HEAD") -> Scope:
    if event != "pull_request":
        return Scope(True, "Manual/non-PR execution: run the full backend suites.")
    try:
        if not base:
            raise ValueError("missing PR base")
        base_commit = git(repo, "rev-parse", "--verify", "--end-of-options", base + "^{commit}").decode().strip()
        head_commit = git(repo, "rev-parse", "--verify", "--end-of-options", head + "^{commit}").decode().strip()
        ancestor = git(repo, "merge-base", base_commit, head_commit).decode().strip()
        raw = git(repo, "diff", "--raw", "--no-abbrev", "--no-renames", "-z", ancestor, head_commit)
        entries = raw.split(b"\0")
        ci_changed = False
        for index in range(0, len(entries) - 1, 2):
            old_mode, new_mode, old_oid, new_oid, status = entries[index].decode("ascii").lstrip(":").split()
            name = entries[index + 1].decode("utf-8", errors="surrogateescape")
            modes = {old_mode, new_mode} - {"000000"}
            if not modes <= REGULAR_MODES or (status == "M" and old_mode != new_mode):
                return Scope(True, "File mode/type changed: run the full backend suites.")
            if name.endswith(".md"):
                continue
            if name in CI_FILES and status in {"A", "M"}:
                ci_changed = True
                continue
            if name.endswith((".yaml", ".yml")) and status == "M":
                if yaml_tokens(git(repo, "cat-file", "blob", old_oid)) == yaml_tokens(git(repo, "cat-file", "blob", new_oid)):
                    continue
            return Scope(True, "Runtime/data or unrecognized changes: run the full backend suites.")
        if ci_changed:
            return Scope(False, "Only documentation, YAML comments/formatting and CI scope infrastructure changed; CI regression tests apply.")
        return Scope(False, "Only Markdown or verified YAML comments/formatting changed; backend tests are unnecessary.")
    except (OSError, subprocess.CalledProcessError, UnicodeError, ValueError, yaml.YAMLError):
        return Scope(True, "Cannot prove a non-runtime diff: run the full backend suites.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--base", default="")
    parser.add_argument("--head", default="HEAD")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args()
    scope = classify(args.repo, event=args.event, base=args.base, head=args.head)
    output = f"run_backend={'true' if scope.run_backend else 'false'}\n"
    print(output + scope.reason)
    if path := os.environ.get("GITHUB_OUTPUT"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(output)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(path).open("a", encoding="utf-8") as stream:
            stream.write(scope.reason + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
