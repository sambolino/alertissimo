import json

from alertissimo.data_layer.representations import (
    InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId,
    InternalRecordId, InternalRecordSource, Portfolio, SemanticRecord,
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
