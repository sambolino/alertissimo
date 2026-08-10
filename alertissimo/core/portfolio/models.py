"""Structural models owned by Portfolio Core.

These models deliberately describe record structure and execution provenance;
broker payload interpretation remains the responsibility of the semantic
mapping layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from alertissimo.core.internal import (
    InternalExecutionId,
    InternalPortfolioId,
    InternalRecordId,
)


@dataclass(frozen=True)
class InternalExecutionProvenance:
    """The physical execution that supplied one or more portfolio records."""

    internal_execution_id: InternalExecutionId
    broker: str | None = None
    origin: str | None = None
    endpoint: str | None = None
    transport: str | None = None


@dataclass(frozen=True)
class InternalRecordSource:
    """The exact location of a record in a broker-native payload."""

    payload_key: str
    payload_path: str
    payload_index: int | None = None


@dataclass(frozen=True)
class InternalRecord:
    """A broker-native record and the context needed to trace its origin."""

    internal_record_id: InternalRecordId
    record_type: str
    payload: Any
    source: InternalRecordSource
    provenance: InternalExecutionProvenance


@dataclass(frozen=True)
class InternalPortfolio:
    """An Alertissimo portfolio containing structurally identified records."""

    internal_portfolio_id: InternalPortfolioId
    records: tuple[InternalRecord, ...] = field(default_factory=tuple)


__all__ = [
    "InternalExecutionProvenance",
    "InternalPortfolio",
    "InternalRecord",
    "InternalRecordSource",
]
