"""Public JSON contract for the final semantic DSL result."""

from types import SimpleNamespace

from alertissimo.api import DSLExecutionResult
from alertissimo.data_layer.representations import InternalPortfolioId, Portfolio


class _Dumpable:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **_kwargs):
        return self.payload


def test_public_json_exports_only_final_semantic_portfolios_as_primary_result():
    portfolio = Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:final")
    )
    run = _Dumpable({"steps": [{"step_index": 1, "state": "succeeded"}]})
    result = SimpleNamespace(
        run=run,
        steps=(
            SimpleNamespace(step_index=0, portfolios=()),
            SimpleNamespace(step_index=1, portfolios=(portfolio,)),
        ),
    )
    execution = DSLExecutionResult(
        source="objects from ztf via alerce",
        surface=_Dumpable({"candidates": {"kind": "objects"}}),
        compilation=SimpleNamespace(
            workflow=_Dumpable({"steps": []}),
            view=_Dumpable({}),
        ),
        staged=object(),
        result=result,
    )

    payload = execution.to_dict()

    assert execution.result_step_index == 1
    assert execution.portfolios == (portfolio,)
    assert payload["result_step_index"] == 1
    assert "steps" not in payload
    assert payload["portfolios"] == [
        {
            "internal_portfolio_id": "portfolio:final",
            "executions": [],
            "records": [],
            "edges": [],
        }
    ]
