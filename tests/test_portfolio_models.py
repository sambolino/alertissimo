from dataclasses import FrozenInstanceError

import pytest

from alertissimo.core.internal import (
    InternalExecutionId,
    InternalPortfolioId,
    InternalRecordId,
)
from alertissimo.core.portfolio import (
    InternalExecutionProvenance,
    InternalPortfolio,
    InternalRecord,
    InternalRecordSource,
)


def test_portfolio_models_preserve_native_payload_and_source_location():
    payload = {"candid": 42}
    provenance = InternalExecutionProvenance(InternalExecutionId("exec_test"))
    source = InternalRecordSource("candidates", "$.candidates", 3)
    record = InternalRecord(
        InternalRecordId("record_test"),
        "detection",
        payload,
        source,
        provenance,
    )
    portfolio = InternalPortfolio(InternalPortfolioId("portfolio_test"), (record,))

    assert portfolio.records[0].payload is payload
    assert portfolio.records[0].source.payload_key == "candidates"
    assert portfolio.records[0].source.payload_path == "$.candidates"
    assert portfolio.records[0].source.payload_index == 3
    with pytest.raises(FrozenInstanceError):
        portfolio.records = ()


def test_execution_provenance_executor_metadata_is_optional():
    provenance = InternalExecutionProvenance(InternalExecutionId("exec_test"))

    assert provenance.broker is None
    assert provenance.origin is None
    assert provenance.endpoint is None
    assert provenance.transport is None


def test_execution_provenance_accepts_executor_metadata():
    provenance = InternalExecutionProvenance(
        InternalExecutionId("exec_test"),
        broker="lasair",
        origin="ztf",
        endpoint="object",
        transport="rest",
    )

    assert provenance.broker == "lasair"
    assert provenance.origin == "ztf"
    assert provenance.endpoint == "object"
    assert provenance.transport == "rest"
