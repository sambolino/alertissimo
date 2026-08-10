"""Temporary exact-command adapter until the real DSL produces endpoint calls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..errors import ExampleCommandError
from ..executor import EndpointExecutor, RegistryEndpointExecutor
from ..models import ExecutionResult
from ..registry import EndpointRegistry
from ..transports.fixture import FixtureTransport


@dataclass(frozen=True)
class ExampleEndpointCall:
    broker: str
    origin: str
    endpoint: str
    params: dict[str, Any]


EXAMPLE_COMMANDS = {
    "get ztf19acmdpyr from fink ztf": ExampleEndpointCall(
        broker="fink",
        origin="ztf",
        endpoint="objects",
        params={
            "objectId": "ZTF19acmdpyr",
            "columns": "i:objectId,i:candid,i:jd,i:magpsf",
        },
    ),
    "get ztf25aazqavg from lasair ztf": ExampleEndpointCall(
        broker="lasair",
        origin="ztf",
        endpoint="object",
        params={"objectId": "ZTF25aazqavg"},
    ),
    "get ztf25aazqavg from antares ztf": ExampleEndpointCall(
        broker="antares",
        origin="ztf",
        endpoint="get_by_ztf_object_id",
        params={"ztf_object_id": "ZTF25aazqavg"},
    ),
}


def execute_example_command(command: str, executor: EndpointExecutor) -> ExecutionResult:
    """Execute one known example; this intentionally is not a general parser."""
    normalized = " ".join(command.strip().lower().split())
    try:
        call = EXAMPLE_COMMANDS[normalized]
    except KeyError as exc:
        known = ", ".join(repr(item) for item in EXAMPLE_COMMANDS)
        raise ExampleCommandError(
            f"unknown example command {command!r}; known commands: {known}"
        ) from exc
    return executor.call(
        broker=call.broker,
        origin=call.origin,
        endpoint=call.endpoint,
        params=dict(call.params),
    )


def build_example_executor() -> RegistryEndpointExecutor:
    """Build a deterministic executor suitable for demos and smoke tests."""
    fixture = FixtureTransport({
        ("fink", "ztf", "objects"): lambda _spec, params: [
            {"i:objectId": params["objectId"], "i:candid": 1}
        ],
        ("lasair", "ztf", "object"): lambda _spec, params: {
            "objectId": params["objectId"],
            "candidates": [],
        },
        ("antares", "ztf", "get_by_ztf_object_id"): lambda _spec, params: {
            "locus_id": f"fixture:{params['ztf_object_id']}",
            "properties": {"ztf_object_id": params["ztf_object_id"]},
            "alerts": [],
        },
    })
    return RegistryEndpointExecutor(
        EndpointRegistry(),
        transports={"rest": fixture, "python": fixture},
    )


__all__ = [
    "EXAMPLE_COMMANDS",
    "ExampleEndpointCall",
    "build_example_executor",
    "execute_example_command",
]
