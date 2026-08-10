from dataclasses import FrozenInstanceError
from datetime import datetime, timezone

import pytest

from alertissimo.core.portfolio import (
    InternalEdgeId, InternalExecutionId, InternalExecutionProvenance,
    InternalPortfolioId, InternalRecordId, InternalRecordSource, Portfolio,
    PortfolioModelError, SemanticEdge, SemanticRecord,
)


def provenance(params=None, headers=None):
    now = datetime.now(timezone.utc)
    return InternalExecutionProvenance(
        InternalExecutionId("exec:one"), "lasair", "ztf", "object",
        {} if params is None else params, now, now, "success",
        sanitized_headers=headers,
    )


def record(value="a", source=None):
    return SemanticRecord(
        InternalRecordId(f"record:{value}"), "detection@ztf:lasair",
        {"identity.source_id": value, "provenance.broker": "lasair"}, source,
    )


def test_repeated_semantic_records_and_helpers():
    a, b = record("a"), record("b")
    portfolio = Portfolio(InternalPortfolioId("portfolio:one"), [a, b])
    assert portfolio.records_of_type("detection@ztf:lasair") == (a, b)
    assert portfolio.get_record(a.internal_record_id) is a
    assert portfolio.semantic_types() == ("detection@ztf:lasair",)
    assert a.get("identity.source_id") == "a" and a.has("provenance.broker")


@pytest.mark.parametrize("key", ["$.objectId", "object@id", "portfolio.records", "a--b"])
def test_relative_field_validation(key):
    with pytest.raises(PortfolioModelError):
        SemanticRecord(InternalRecordId("record:a"), "x", {key: 1})


def test_first_class_edges_and_target_validation():
    a, b = record("a"), record("b")
    edge = SemanticEdge(InternalEdgeId("edge:one"), "--followup_of-->",
                        a.internal_record_id, b.internal_record_id,
                        {"provenance.broker": "lasair"})
    association = SemanticEdge(InternalEdgeId("edge:two"), "--association--",
                               b.internal_record_id, a.internal_record_id)
    p = Portfolio(InternalPortfolioId("portfolio:one"), [a, b], [edge, association])
    assert p.get_edge(edge.internal_edge_id) is edge
    assert p.edges_of_type("--association--") == (association,)
    with pytest.raises(PortfolioModelError):
        Portfolio(InternalPortfolioId("portfolio:bad"), [a], [edge])
    with pytest.raises(PortfolioModelError):
        SemanticEdge(InternalEdgeId("edge:bad"), "associated_with",
                     a.internal_record_id, b.internal_record_id)


def test_execution_provenance_is_call_scoped_and_required_when_listed():
    source = InternalRecordSource(InternalExecutionId("exec:one"), "$.object")
    item = record("a", source)
    call = provenance()
    p = Portfolio(InternalPortfolioId("portfolio:one"), [item], executions=[call])
    assert p.execution(call.internal_execution_id) is call
    with pytest.raises(PortfolioModelError):
        Portfolio(InternalPortfolioId("portfolio:bad"), [item], executions=[
            InternalExecutionProvenance(InternalExecutionId("exec:other"), call.broker,
                call.origin, call.endpoint, {}, call.started_at, call.finished_at, "success")])


def test_duplicate_ids_and_defensive_copying():
    a = record("a")
    with pytest.raises(PortfolioModelError):
        Portfolio(InternalPortfolioId("portfolio:one"), [a, a])
    values = {"identity.source_id": "a"}
    r = SemanticRecord(InternalRecordId("record:copy"), "detection@ztf:lasair", values)
    values["later"] = True
    assert "later" not in r.fields
    params, headers = {"a": 1}, {"Authorization": "redacted"}
    call = provenance(params, headers)
    params["b"] = 2; headers["secret"] = "bad"
    assert dict(call.params) == {"a": 1}
    assert dict(call.sanitized_headers) == {"Authorization": "redacted"}
    with pytest.raises(TypeError):
        call.params["x"] = 1
    with pytest.raises(FrozenInstanceError):
        r.semantic_type = "changed"
