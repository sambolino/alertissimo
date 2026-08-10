"""Fetch ZTF19acmdpyr detections from the Fink/ZTF objects endpoint."""

import json
from pprint import pprint

from alertissimo.core.brokers.execution.examples import execute_example_command
from alertissimo.core.brokers.execution.executor import (
    EndpointExecutor,
    RegistryEndpointExecutor,
)
from alertissimo.core.brokers.execution.models import ExecutionResult
from alertissimo.core.brokers.execution.registry import EndpointRegistry
from alertissimo.core.brokers.execution.transports import RestTransport


def build_live_executor() -> RegistryEndpointExecutor:
    """Build an executor that calls the public Fink/ZTF REST API."""
    return RegistryEndpointExecutor(
        EndpointRegistry(),
        transports={"rest": RestTransport()},
    )


def run(executor: EndpointExecutor | None = None) -> ExecutionResult:
    """Execute the hardcoded object lookup and return the complete Fink response."""
    return execute_example_command(
        "get ZTF19acmdpyr from fink ztf",
        executor or build_live_executor(),
    )


def main() -> ExecutionResult:
    result = run()
    print("request:")
    pprint(result.execution_provenance)
    print(f"internal_execution_id: {result.internal_execution_id}")
    print("execution:")
    print(f"  broker: {result.execution_provenance.broker}")
    print(f"  origin: {result.execution_provenance.origin}")
    print(f"  endpoint: {result.execution_provenance.endpoint}")
    print(f"  transport: {result.execution_provenance.transport}")
    print(f"  started_at: {result.execution_provenance.started_at}")
    print(f"  finished_at: {result.execution_provenance.finished_at}")
    print(f"  elapsed_ms: {result.execution_provenance.elapsed_ms}")
    print("response metadata:")
    pprint(result.execution_provenance)
    print("Fink/ZTF JSON response:")
    print(json.dumps(result.payload, indent=2))
    return result


if __name__ == "__main__":
    main()
