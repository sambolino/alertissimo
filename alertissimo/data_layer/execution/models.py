"""Public value objects used by endpoint execution."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping

from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance


class _ReplayableIterator(Iterator[Any]):
    """Lazily cache a one-shot physical result so later consumers see the same rows.

    Python-client search APIs may return generators or other iterators. Alertissimo
    can legitimately inspect one physical execution more than once during a staged
    workflow: first to expose runtime candidate identities and later to build the
    occurrence-aligned normalized result. Retaining a replayable physical payload
    keeps those reads deterministic without eagerly materializing the provider
    stream at call time.
    """

    def __init__(self, source: Iterator[Any]) -> None:
        self._source = source
        self._cache: list[Any] = []
        self._exhausted = False
        self._next_index = 0

    def _iterate_from_start(self) -> Iterator[Any]:
        index = 0
        while True:
            if index < len(self._cache):
                item = self._cache[index]
            elif self._exhausted:
                return
            else:
                try:
                    item = next(self._source)
                except StopIteration:
                    self._exhausted = True
                    return
                self._cache.append(item)
            index += 1
            yield item

    def __iter__(self) -> Iterator[Any]:
        return self._iterate_from_start()

    def __next__(self) -> Any:
        if self._next_index < len(self._cache):
            item = self._cache[self._next_index]
        elif self._exhausted:
            raise StopIteration
        else:
            try:
                item = next(self._source)
            except StopIteration:
                self._exhausted = True
                raise
            self._cache.append(item)
        self._next_index += 1
        return item


@dataclass(frozen=True)
class EndpointSpec:
    broker: str
    origin: str
    endpoint: str
    transport_kind: str
    params: Mapping[str, Any] = field(default_factory=dict)
    fixed_params: Mapping[str, Any] = field(default_factory=dict)
    method: str | None = None
    url: str | None = None
    module: str | None = None
    client: str | None = None
    client_method: str | None = None
    headers: Mapping[str, Any] = field(default_factory=dict)
    request_encoding: str = "json"

    def __post_init__(self) -> None:
        if self.request_encoding not in {"json", "form"}:
            raise ValueError(
                f"unsupported REST request encoding: {self.request_encoding}"
            )
        for name in ("params", "fixed_params", "headers"):
            object.__setattr__(self, name, MappingProxyType(dict(getattr(self, name))))


@dataclass(frozen=True)
class TransportResult:
    payload: Any
    method: str | None = None
    url: str | None = None
    status_code: int | None = None
    content_type: str | None = None
    sanitized_headers: Mapping[str, str] | None = None
    raw_size_bytes: int | None = None


@dataclass(frozen=True)
class ExecutionResult:
    payload: Any
    execution_provenance: InternalExecutionProvenance

    def __post_init__(self) -> None:
        if isinstance(self.payload, Iterator) and not isinstance(
            self.payload, _ReplayableIterator
        ):
            object.__setattr__(self, "payload", _ReplayableIterator(self.payload))

    @property
    def internal_execution_id(self) -> InternalExecutionId:
        return self.execution_provenance.internal_execution_id
