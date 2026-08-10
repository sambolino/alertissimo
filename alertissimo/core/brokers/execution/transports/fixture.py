"""Deterministic, credential-free endpoint execution for tests and examples."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from ..errors import FixtureNotFoundError
from ..models import EndpointSpec, TransportResult

EndpointKey = tuple[str, str, str]
FixtureFactory = Callable[[EndpointSpec, dict[str, Any]], Any | TransportResult]
FixtureValue = Any | FixtureFactory


class FixtureTransport:
    """Return registered broker-native fixture payloads without transforming them."""

    name = "fixture"

    def __init__(self, fixtures: Mapping[EndpointKey, FixtureValue]):
        self._fixtures = dict(fixtures)

    def execute(
        self,
        *,
        spec: EndpointSpec,
        params: dict[str, Any],
    ) -> TransportResult:
        key = (spec.broker, spec.origin, spec.name)
        try:
            fixture = self._fixtures[key]
        except KeyError as exc:
            logical_name = "/".join(key)
            raise FixtureNotFoundError(f"no fixture registered for {logical_name}") from exc

        value = fixture(spec, dict(params)) if callable(fixture) else fixture
        if isinstance(value, TransportResult):
            return value
        return TransportResult(payload=value, method=spec.method, url=spec.url)


__all__ = ["EndpointKey", "FixtureFactory", "FixtureTransport", "FixtureValue"]
