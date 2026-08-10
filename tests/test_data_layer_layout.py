"""Compatibility checks for the frozen data-layer layout."""


def test_old_data_layer_import_paths_remain_compatible():
    from alertissimo.core.portfolio import Portfolio
    from alertissimo.core.brokers.execution import ExecutionResult
    from alertissimo.core.brokers.execution.registry import EndpointRegistry
    from alertissimo.data_layer.representations import Portfolio as NewPortfolio
    from alertissimo.data_layer.execution import ExecutionResult as NewExecutionResult
    from alertissimo.data_layer.execution.registry import (
        EndpointRegistry as NewEndpointRegistry,
    )

    assert Portfolio is NewPortfolio
    assert ExecutionResult is NewExecutionResult
    assert EndpointRegistry is NewEndpointRegistry
