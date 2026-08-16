"""Physical execution substitutes used by the smoke scenarios."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
)

FIXTURE_ROOT = Path(__file__).with_name("fixtures")


class FixtureEndpointExecutor:
    """Validate physical calls and return only their explicitly registered fixture."""

    def __init__(
        self,
        fixtures: Mapping[tuple[str, str, str, tuple[tuple[str, Any], ...]], str],
        *,
        fail_call: int | None = None,
    ) -> None:
        self.fixtures = dict(fixtures)
        self.fail_call = fail_call
        self.calls: list[tuple[str, str, str, dict[str, Any]]] = []

    @staticmethod
    def key(broker: str, origin: str, endpoint: str, params: Mapping[str, Any]):
        return broker, origin, endpoint, tuple(sorted(params.items()))

    def execute(
        self, broker: str, origin: str, endpoint: str, params=None, headers=None
    ) -> ExecutionResult:
        if headers is not None:
            raise AssertionError(
                "fixture execution never accepts authentication headers"
            )
        supplied = dict(params or {})
        self.calls.append((broker, origin, endpoint, supplied))
        call_number = len(self.calls)
        if self.fail_call == call_number:
            raise RuntimeError(
                f"controlled fixture failure on physical call {call_number}"
            )
        key = self.key(broker, origin, endpoint, supplied)
        try:
            fixture_name = self.fixtures[key]
        except KeyError as error:
            raise AssertionError(
                f"unexpected fixture call {broker}/{origin}/{endpoint} with {supplied!r}"
            ) from error
        payload = json.loads((FIXTURE_ROOT / fixture_name).read_text(encoding="utf-8"))
        execution_id = InternalExecutionId(f"execution:smoke:{call_number}")
        return ExecutionResult(
            payload=payload,
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=execution_id,
                broker=broker,
                origin=origin,
                endpoint=endpoint,
                params=supplied,
                status="success",
                transport="fixture",
            ),
        )


def fixture_key(broker: str, origin: str, endpoint: str, **params: Any):
    return FixtureEndpointExecutor.key(broker, origin, endpoint, params)
