"""Immutable products of declarative orchestration parameter binding."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from alertissimo.data_layer.execution.models import EndpointSpec
from alertissimo.orchestration.runtime.models import EndpointPlan


@dataclass(frozen=True)
class BoundEndpointCall:
    """A selected physical endpoint and its invocation-supplied parameters.

    Defaults and fixed parameters remain on ``EndpointSpec`` for the executor to
    apply using its existing precedence rules.  No Step is copied into this value.
    """

    endpoint_plan: EndpointPlan
    endpoint_spec: EndpointSpec
    params: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "params", MappingProxyType(dict(self.params)))


@dataclass(frozen=True)
class StepBindingResult:
    """Bound calls belonging to one positional Step occurrence."""

    step_index: int
    bound_calls: tuple[BoundEndpointCall, ...]


__all__ = ["BoundEndpointCall", "StepBindingResult"]
