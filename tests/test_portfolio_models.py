"""Contract tests for the canonical internal portfolio representation."""

from dataclasses import FrozenInstanceError

import pytest

from alertissimo.core.portfolio import (
    InternalEdgeId, InternalExecutionId, InternalExecutionProvenance,
    InternalPortfolioId, InternalRecordId, InternalRecordSource, Portfolio,
    PortfolioModelError, SemanticEdge, SemanticRecord,
)


def source(index=None):
    return InternalRecordSource(
        InternalExecutionId("exec:1"), "objects", "$.objects", index
    )


def record(value, identifier="record:1"):
    return SemanticRecord(
        InternalRecordId(identifier), "alert.detection", {"flux.value": value}, source()
    )


def execution(identifier="exec:1"):
    return InternalExecutionProvenance(
        InternalExecutionId(identifier), "lasair", "ztf", "object",
        {"objectId": "ZTF1"}, transport="fixture",
    )


def test_repeated_semantic_records_are_first_class():
    portfolio = Portfolio(
        InternalPortfolioId("portfolio:1"),
        records=(record(1, "record:1"), record(2, "record:2")),
        executions=(execution(),),
    )
    assert [item.semantic_type for item in portfolio.records] == [
        "alert.detection", "alert.detection"
    ]


def test_fields_use_relative_paths():
    assert record(3).fields["flux.value"] == 3
    with pytest.raises(PortfolioModelError, match="relative"):
        SemanticRecord(InternalRecordId("record:1"), "alert", {"$.flux": 3}, source())


def test_edges_are_first_class_and_keep_fields():
    records = (record(1, "record:1"), record(2, "record:2"))
    edge = SemanticEdge(
        InternalEdgeId("edge:1"), "associated_with", records[0].internal_record_id,
        records[1].internal_record_id, {"separation.arcsec": 0.2}, source(),
    )
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), records, (edge,), (execution(),))
    assert portfolio.edges[0].edge_type == "associated_with"
    assert portfolio.edges[0].fields == {"separation.arcsec": 0.2}


def test_edge_target_must_exist():
    edge = SemanticEdge(
        InternalEdgeId("edge:1"), "associated_with", InternalRecordId("record:1"),
        InternalRecordId("record:missing"), {}, source(),
    )
    with pytest.raises(PortfolioModelError, match="target"):
        Portfolio(InternalPortfolioId("portfolio:1"), (record(1),), (edge,), (execution(),))


def test_semantic_provenance_is_an_ordinary_field():
    item = SemanticRecord(
        InternalRecordId("record:1"), "classification",
        {"classification.source": "broker"}, source(),
    )
    assert item.fields["classification.source"] == "broker"


def test_execution_provenance_is_internal_and_call_scoped():
    provenance = execution()
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), executions=(provenance,))
    assert portfolio.executions == (provenance,)
    assert not hasattr(portfolio, "execution_provenance")


def test_no_eager_field_level_provenance():
    assert record(1).fields == {"flux.value": 1}


@pytest.mark.parametrize("member", ["record", "edge", "execution"])
def test_duplicate_ids_are_rejected(member):
    kwargs = {"records": (), "edges": (), "executions": ()}
    if member == "record":
        kwargs["records"] = (record(1), record(2))
    elif member == "edge":
        records = (record(1, "record:1"), record(2, "record:2"))
        kwargs["records"] = records
        edge = SemanticEdge(InternalEdgeId("edge:1"), "x", records[0].internal_record_id,
                            records[1].internal_record_id, {}, source())
        kwargs["edges"] = (edge, edge)
    else:
        kwargs["executions"] = (execution(), execution())
    with pytest.raises(PortfolioModelError, match="duplicate"):
        Portfolio(InternalPortfolioId("portfolio:1"), **kwargs)


def test_inputs_are_defensively_copied_and_objects_are_frozen():
    fields = {"nested": {"value": 1}}
    item = SemanticRecord(InternalRecordId("record:1"), "alert", fields, source())
    fields["nested"]["value"] = 2
    assert item.fields["nested"]["value"] == 1
    with pytest.raises(FrozenInstanceError):
        item.semantic_type = "changed"


def test_convenience_helpers_find_records_and_executions():
    portfolio = Portfolio(
        InternalPortfolioId("portfolio:1"), (record(1),), executions=(execution(),)
    )
    assert portfolio.record(InternalRecordId("record:1")) is portfolio.records[0]
    assert portfolio.execution(InternalExecutionId("exec:1")) is portfolio.executions[0]
