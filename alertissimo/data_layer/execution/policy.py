"""Load declarative physical-execution policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


DEFAULT_EXECUTION_POLICY_PATH = Path(__file__).with_name("policy.yaml")


class ExecutionPolicyError(ValueError):
    """The declarative execution policy is missing or invalid."""


@dataclass(frozen=True)
class ExecutionPolicy:
    """Validated runtime representation of declarative execution limits."""

    default_auto_page_size: int
    max_auto_pages: int
    source_path: Path


def _positive_int(value: Any, *, name: str) -> int:
    if isinstance(value, bool):
        raise ExecutionPolicyError(f"{name} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ExecutionPolicyError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise ExecutionPolicyError(f"{name} must be a positive integer")
    return parsed


def _mapping(value: Any, *, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ExecutionPolicyError(f"{name} must be a mapping")
    return value


def load_execution_policy(path: str | Path | None = None) -> ExecutionPolicy:
    """Load and validate the physical-execution policy from YAML."""

    source = Path(path) if path is not None else DEFAULT_EXECUTION_POLICY_PATH
    try:
        with source.open(encoding="utf-8") as stream:
            document = yaml.safe_load(stream) or {}
    except OSError as exc:
        raise ExecutionPolicyError(f"cannot read execution policy: {source}") from exc

    root = _mapping(document, name="execution policy")
    if root.get("version") != 1:
        raise ExecutionPolicyError("execution policy version must be 1")
    pagination = _mapping(root.get("pagination"), name="execution policy pagination")

    return ExecutionPolicy(
        default_auto_page_size=_positive_int(
            pagination.get("default_auto_page_size"),
            name="pagination.default_auto_page_size",
        ),
        max_auto_pages=_positive_int(
            pagination.get("max_auto_pages"),
            name="pagination.max_auto_pages",
        ),
        source_path=source,
    )


__all__ = [
    "DEFAULT_EXECUTION_POLICY_PATH",
    "ExecutionPolicy",
    "ExecutionPolicyError",
    "load_execution_policy",
]
