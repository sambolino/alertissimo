import json

from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    InternalRecordSource,
    Portfolio,
    SemanticEdge,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict, portfolio_to_json


def test_portfolio_serialization_is_plain_and_excludes_raw_payload():
    execution_id = InternalExecutionId("exec:1")
    execution = InternalExecutionProvenance(execution_id, "lasair", "ztf", "object", {"objectId": "ZTF1"}, status="success")
    record = SemanticRecord(InternalRecordId("record:1"), "summary@ztf:lasair", {"identity.object_id": "ZTF1"}, InternalRecordSource(execution_id, "object", "."))
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), (record,), executions=(execution,))
    result = portfolio_to_dict(portfolio)
    assert result["internal_portfolio_id"] == "portfolio:1"
    assert isinstance(result["records"][0]["fields"], dict)
    assert result["executions"][0]["internal_execution_id"] == "exec:1"
    assert "raw_provider_payload" not in result
    assert json.loads(portfolio_to_json(portfolio)) == result


def test_native_python_client_parameters_serialize_as_stable_text():
    class NativeCoordinate:
        def __str__(self):
            return "ICRS(124.88deg,-6.02deg)"

    execution = InternalExecutionProvenance(
        InternalExecutionId("exec:native"),
        "antares",
        "ztf",
        "cone_search",
        {"center": NativeCoordinate(), "radius": 1.0},
        status="success",
    )
    portfolio = Portfolio(
        InternalPortfolioId("portfolio:native"),
        executions=(execution,),
    )

    result = portfolio_to_dict(portfolio)
    assert result["executions"][0]["params"] == {
        "center": "ICRS(124.88deg,-6.02deg)",
        "radius": 1.0,
    }
    assert json.loads(portfolio_to_json(portfolio)) == result


def test_record_edge_serialization_keeps_existing_endpoint_keys():
    first = SemanticRecord(InternalRecordId("record:1"), "summary@ztf:lasair", {})
    second = SemanticRecord(InternalRecordId("record:2"), "detection@ztf:lasair", {})
    edge = SemanticEdge(
        InternalEdgeId("edge:record"),
        "--association--",
        first.internal_record_id,
        second.internal_record_id,
    )

    result = portfolio_to_dict(
        Portfolio(InternalPortfolioId("portfolio:1"), (first, second), (edge,))
    )["edges"][0]

    assert result["subject_record_id"] == "record:1"
    assert result["target_record_id"] == "record:2"
    assert "subject_portfolio_id" not in result
    assert "target_portfolio_id" not in result


def test_portfolio_edge_serialization_uses_portfolio_endpoint_keys():
    local = InternalPortfolioId("portfolio:galaxy")
    edge = SemanticEdge(
        InternalEdgeId("edge:portfolio"),
        "--spatially_near--",
        local,
        InternalPortfolioId("portfolio:star"),
        {"angular_separation": 0.7},
    )

    result = portfolio_to_dict(Portfolio(local, edges=(edge,)))["edges"][0]

    assert result["subject_portfolio_id"] == "portfolio:galaxy"
    assert result["target_portfolio_id"] == "portfolio:star"
    assert result["fields"] == {"angular_separation": 0.7}
    assert "subject_record_id" not in result
    assert "target_record_id" not in result
