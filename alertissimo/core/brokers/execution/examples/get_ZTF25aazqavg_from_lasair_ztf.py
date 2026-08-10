"""Fetch the ZTF25aazqavg object from the live Lasair/ZTF endpoint."""

import json
from pprint import pprint

from alertissimo.core.brokers.execution.examples import (
    execute_example_command,
)
from alertissimo.core.brokers.execution.credentials import default_credential_resolver
from alertissimo.core.brokers.execution.executor import (
    EndpointExecutor,
    RegistryEndpointExecutor,
)
from alertissimo.core.brokers.execution.models import ExecutionResult
from alertissimo.core.brokers.execution.registry import EndpointRegistry
from alertissimo.core.brokers.execution.transports import RestTransport


def build_live_executor() -> RegistryEndpointExecutor:
    """Build an authenticated executor for the Lasair/ZTF REST API."""
    return RegistryEndpointExecutor(
        EndpointRegistry(),
        transports={
            "rest": RestTransport(
                credential_resolver=default_credential_resolver(),
            ),
        },
    )


def run(executor: EndpointExecutor | None = None) -> ExecutionResult:
    """Execute the hardcoded command and return the complete Lasair response."""
    return execute_example_command(
        "get ZTF25aazqavg from lasair ztf",
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
    print(f"  completed_at: {result.execution_provenance.completed_at}")
    print(f"  elapsed_ms: {result.execution_provenance.elapsed_ms}")
    print("response metadata:")
    pprint(result.execution_provenance)
    print("Lasair/ZTF JSON response:")
    print(json.dumps(result.payload, indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
