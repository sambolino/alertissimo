"""In-memory representation of an Alertissimo semantic portfolio.

Semantic provenance remains part of record- or edge-scoped ``fields``.  The
execution and source models in this module instead describe Alertissimo's own
call-scoped audit metadata.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, TypeAlias


class PortfolioModelError(ValueError):
    """Raised when an internal portfolio model is structurally invalid."""


def _require_non_empty_string(value: Any, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise PortfolioModelError(f"{name} must be a non-empty string")


def _immutable_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PortfolioModelError(f"{name} must be a mapping")
    return MappingProxyType(dict(value))


def _validate_relative_fields(fields: Mapping[str, Any], name: str) -> None:
    for field_path in fields:
        _require_non_empty_string(field_path, f"{name} key")
        if (
            "@" in field_path
            or field_path.startswith("portfolio.")
            or field_path.startswith("--")
        ):
            raise PortfolioModelError(
                f"{name} key {field_path!r} must be relative to its semantic object"
            )


@dataclass(frozen=True)
class InternalPortfolioId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.value, "internal portfolio ID")


@dataclass(frozen=True)
class InternalRecordId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.value, "internal record ID")


@dataclass(frozen=True)
class InternalEdgeId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.value, "internal edge ID")


@dataclass(frozen=True)
class InternalExecutionId:
    value: str

    def __post_init__(self) -> None:
        _require_non_empty_string(self.value, "internal execution ID")


InternalEdgeEndpoint: TypeAlias = InternalPortfolioId | InternalRecordId


@dataclass(frozen=True)
class InternalRecordSource:
    internal_execution_id: InternalExecutionId
    payload_key: str
    payload_path: str
    payload_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.internal_execution_id, InternalExecutionId):
            raise PortfolioModelError("internal_execution_id must be an InternalExecutionId")
        _require_non_empty_string(self.payload_key, "payload_key")
        _require_non_empty_string(self.payload_path, "payload_path")
        if self.payload_index is not None and (
            not isinstance(self.payload_index, int)
            or isinstance(self.payload_index, bool)
            or self.payload_index < 0
        ):
            raise PortfolioModelError("payload_index must be a non-negative integer or None")


@dataclass(frozen=True)
class InternalExecutionProvenance:
    internal_execution_id: InternalExecutionId
    broker: str
    origin: str
    endpoint: str
    params: Mapping[str, Any] = field(default_factory=dict)
    status: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    payload_fingerprint: str | None = None
    registry_version: str | None = None
    adapter_version: str | None = None
    elapsed_ms: float | None = None
    transport: str | None = None
    method: str | None = None
    url: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    response_status_code: int | None = None
    response_content_type: str | None = None
    raw_size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.internal_execution_id, InternalExecutionId):
            raise PortfolioModelError("internal_execution_id must be an InternalExecutionId")
        for name in ("broker", "origin", "endpoint"):
            _require_non_empty_string(getattr(self, name), name)
        if self.status is not None and not isinstance(self.status, str):
            raise PortfolioModelError("status must be a string or None")
        object.__setattr__(self, "params", _immutable_mapping(self.params, "params"))
        if self.sanitized_headers is not None:
            object.__setattr__(
                self,
                "sanitized_headers",
                _immutable_mapping(self.sanitized_headers, "sanitized_headers"),
            )


@dataclass(frozen=True)
class SemanticRecord:
    internal_record_id: InternalRecordId
    semantic_type: str
    fields: Mapping[str, Any]
    internal_source: InternalRecordSource | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.internal_record_id, InternalRecordId):
            raise PortfolioModelError("internal_record_id must be an InternalRecordId")
        _require_non_empty_string(self.semantic_type, "semantic_type")
        immutable_fields = _immutable_mapping(self.fields, "fields")
        _validate_relative_fields(immutable_fields, "record field")
        if self.internal_source is not None and not isinstance(
            self.internal_source, InternalRecordSource
        ):
            raise PortfolioModelError("internal_source must be an InternalRecordSource or None")
        object.__setattr__(self, "fields", immutable_fields)

    def get(self, field_path: str, default: Any = None) -> Any:
        """Return a relative semantic field, or ``default`` when it is absent."""
        return self.fields.get(field_path, default)

    def has(self, field_path: str) -> bool:
        """Return whether a relative semantic field is present."""
        return field_path in self.fields


@dataclass(frozen=True)
class SemanticEdge:
    internal_edge_id: InternalEdgeId
    edge_type: str
    subject: InternalEdgeEndpoint
    target: InternalEdgeEndpoint
    fields: Mapping[str, Any] = field(default_factory=dict)
    internal_source: InternalRecordSource | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.internal_edge_id, InternalEdgeId):
            raise PortfolioModelError("internal_edge_id must be an InternalEdgeId")
        _require_non_empty_string(self.edge_type, "edge_type")
        if not self.edge_type.startswith("--") or "--" not in self.edge_type[2:]:
            raise PortfolioModelError("edge_type must use a connection-plane --edge-- symbol")
        endpoint_types = (InternalPortfolioId, InternalRecordId)
        if not isinstance(self.subject, endpoint_types):
            raise PortfolioModelError(
                "edge subject must be an InternalPortfolioId or InternalRecordId"
            )
        if not isinstance(self.target, endpoint_types):
            raise PortfolioModelError(
                "edge target must be an InternalPortfolioId or InternalRecordId"
            )
        if type(self.subject) is not type(self.target):
            raise PortfolioModelError(
                "edge endpoints must both be portfolio IDs or both be record IDs"
            )
        immutable_fields = _immutable_mapping(self.fields, "fields")
        _validate_relative_fields(immutable_fields, "edge field")
        if self.internal_source is not None and not isinstance(
            self.internal_source, InternalRecordSource
        ):
            raise PortfolioModelError("internal_source must be an InternalRecordSource or None")
        object.__setattr__(self, "fields", immutable_fields)

    def get(self, field_path: str, default: Any = None) -> Any:
        """Return a relative edge field, or ``default`` when it is absent."""
        return self.fields.get(field_path, default)

    def has(self, field_path: str) -> bool:
        """Return whether a relative edge field is present."""
        return field_path in self.fields


@dataclass(frozen=True)
class Portfolio:
    internal_portfolio_id: InternalPortfolioId
    records: tuple[SemanticRecord, ...] = ()
    edges: tuple[SemanticEdge, ...] = ()
    executions: tuple[InternalExecutionProvenance, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.internal_portfolio_id, InternalPortfolioId):
            raise PortfolioModelError("internal_portfolio_id must be an InternalPortfolioId")
        self._validate_tuple(self.records, SemanticRecord, "records")
        self._validate_tuple(self.edges, SemanticEdge, "edges")
        self._validate_tuple(
            self.executions, InternalExecutionProvenance, "executions"
        )

        record_ids = self._unique_ids(
            (record.internal_record_id for record in self.records), "record"
        )
        self._unique_ids((edge.internal_edge_id for edge in self.edges), "edge")
        execution_ids = self._unique_ids(
            (execution.internal_execution_id for execution in self.executions),
            "execution",
        )

        for edge in self.edges:
            if isinstance(edge.subject, InternalRecordId):
                if edge.subject not in record_ids:
                    raise PortfolioModelError(
                        f"edge subject record {edge.subject.value!r} does not exist"
                    )
                if edge.target not in record_ids:
                    raise PortfolioModelError(
                        f"edge target record {edge.target.value!r} does not exist"
                    )
            elif self.internal_portfolio_id not in (edge.subject, edge.target):
                raise PortfolioModelError(
                    "portfolio edge is not incident on the portfolio that stores it"
                )

        if self.executions:
            for item in (*self.records, *self.edges):
                if (
                    item.internal_source is not None
                    and item.internal_source.internal_execution_id not in execution_ids
                ):
                    raise PortfolioModelError(
                        "internal source references an execution not stored in the portfolio"
                    )

    @staticmethod
    def _validate_tuple(value: Any, item_type: type[Any], name: str) -> None:
        if not isinstance(value, tuple) or any(
            not isinstance(item, item_type) for item in value
        ):
            raise PortfolioModelError(
                f"{name} must be a tuple of {item_type.__name__} objects"
            )

    @staticmethod
    def _unique_ids(values: Any, kind: str) -> set[Any]:
        identifiers: set[Any] = set()
        for identifier in values:
            if identifier in identifiers:
                raise PortfolioModelError(f"duplicate internal {kind} ID: {identifier.value!r}")
            identifiers.add(identifier)
        return identifiers

    def records_of_type(self, semantic_type: str) -> tuple[SemanticRecord, ...]:
        return tuple(record for record in self.records if record.semantic_type == semantic_type)

    def get_record(
        self, internal_record_id: InternalRecordId | str
    ) -> SemanticRecord | None:
        value = (
            internal_record_id.value
            if isinstance(internal_record_id, InternalRecordId)
            else internal_record_id
        )
        return next(
            (record for record in self.records if record.internal_record_id.value == value),
            None,
        )

    def get_edge(self, internal_edge_id: InternalEdgeId | str) -> SemanticEdge | None:
        value = (
            internal_edge_id.value
            if isinstance(internal_edge_id, InternalEdgeId)
            else internal_edge_id
        )
        return next(
            (edge for edge in self.edges if edge.internal_edge_id.value == value), None
        )

    def semantic_types(self) -> tuple[str, ...]:
        return tuple(sorted({record.semantic_type for record in self.records}))

    def edges_of_type(self, edge_type: str) -> tuple[SemanticEdge, ...]:
        return tuple(edge for edge in self.edges if edge.edge_type == edge_type)

    def execution(
        self, internal_execution_id: InternalExecutionId | str
    ) -> InternalExecutionProvenance | None:
        value = (
            internal_execution_id.value
            if isinstance(internal_execution_id, InternalExecutionId)
            else internal_execution_id
        )
        return next(
            (
                execution
                for execution in self.executions
                if execution.internal_execution_id.value == value
            ),
            None,
        )
