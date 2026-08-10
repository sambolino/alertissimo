"""Build canonical semantic portfolios from physical endpoint executions."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    InternalRecordSource,
    Portfolio,
    SemanticRecord,
)

from .capability_graph import split_semantic_path
from .mapping_schema import validate_mapping_file
from .payload_paths import RawFieldMissing, extract_raw_field, resolve_payload_items


def new_internal_portfolio_id() -> InternalPortfolioId:
    return InternalPortfolioId(f"portfolio:{uuid4().hex}")


def new_internal_record_id() -> InternalRecordId:
    return InternalRecordId(f"record:{uuid4().hex}")


def _apply_transform(value: Any, specification: Mapping[str, Any] | None) -> Any:
    if not specification:
        return value
    transform_type = specification["type"]
    if transform_type == "boolean_not":
        return not bool(value)
    if transform_type == "value_map":
        return specification["map"].get(value, value)
    if transform_type == "jd_to_mjd":
        return value - 2400000.5
    return value  # The mapping schema rejects unknown transform types.


def build_portfolio_from_execution(
    execution: ExecutionResult,
    *,
    mappings_path: Path,
    internal_portfolio_id: InternalPortfolioId | None = None,
    record_id_factory: Callable[[], InternalRecordId] | None = None,
) -> Portfolio:
    """Interpret one provider mapping and transform an execution's raw payload."""
    mappings_path = Path(mappings_path)
    validate_mapping_file(mappings_path)
    with mappings_path.open(encoding="utf-8") as stream:
        document = yaml.safe_load(stream)

    payload_definitions = document["payloads"]
    mappings = document["mappings"]
    transforms = document.get("transforms", {})
    records: list[SemanticRecord] = []
    make_record_id = record_id_factory or new_internal_record_id

    # TODO: validate semantic_type and relative field paths against
    # data_layer/semantic_model/ontology.yaml once the ordered ontology loader exists.
    for payload_key, payload_definition in payload_definitions.items():
        payload_path = payload_definition["path"]
        items = resolve_payload_items(
            execution.payload,
            payload_key=payload_key,
            payload_path=payload_path,
        )
        for item in items:
            fields_by_type: dict[str, dict[str, Any]] = {}
            for semantic_path, references in mappings.items():
                semantic_type, relative_field = split_semantic_path(semantic_path)
                for raw_reference in references:
                    ref_payload_key, raw_field = raw_reference.split("#", 1)
                    if ref_payload_key != payload_key:
                        continue
                    try:
                        value = extract_raw_field(item.value, raw_field)
                    except RawFieldMissing:
                        continue
                    specification = transforms.get(semantic_path, {}).get(raw_reference)
                    fields_by_type.setdefault(semantic_type, {})[relative_field] = (
                        _apply_transform(value, specification)
                    )
                    break

            for semantic_type, fields in fields_by_type.items():
                if not fields:
                    continue
                records.append(
                    SemanticRecord(
                        internal_record_id=make_record_id(),
                        semantic_type=semantic_type,
                        fields=fields,
                        internal_source=InternalRecordSource(
                            internal_execution_id=execution.internal_execution_id,
                            payload_key=payload_key,
                            payload_path=payload_path,
                            payload_index=item.payload_index,
                        ),
                    )
                )

    return Portfolio(
        internal_portfolio_id=internal_portfolio_id or new_internal_portfolio_id(),
        records=tuple(records),
        edges=(),
        executions=(execution.execution_provenance,),
    )
