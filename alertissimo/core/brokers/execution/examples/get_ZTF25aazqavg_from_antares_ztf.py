"""Fetch the ZTF25aazqavg locus from the ANTARES/ZTF Python client."""

import json
from pprint import pprint

from alertissimo.core.brokers.execution.examples import (
    execute_example_command,
)
from alertissimo.core.brokers.execution.executor import (
    EndpointExecutor,
    RegistryEndpointExecutor,
)
from alertissimo.core.brokers.execution.models import ExecutionResult
from alertissimo.core.brokers.execution.registry import EndpointRegistry
from alertissimo.core.brokers.execution.transports import PythonClientTransport


def build_live_executor() -> RegistryEndpointExecutor:
    """Build an executor backed by the official ANTARES Python client."""
    return RegistryEndpointExecutor(
        EndpointRegistry(),
        transports={"python": PythonClientTransport()},
    )


def run(executor: EndpointExecutor | None = None) -> ExecutionResult:
    """Execute the hardcoded command and return the original ANTARES locus."""
    return execute_example_command(
        "get ZTF25aazqavg from antares ztf",
        executor or build_live_executor(),
    )


def locus_json_view(locus: object) -> object:
    """Create a JSON-printable view without changing the executor payload."""
    if locus is None:
        return None
    fields = (
        "locus_id",
        "ra",
        "dec",
        "properties",
        "tags",
        "catalogs",
        "watch_list_ids",
        "watch_object_ids",
        "grav_wave_events",
    )
    return {name: getattr(locus, name) for name in fields}


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
    print("ANTARES/ZTF JSON response:")
    print(json.dumps(locus_json_view(result.payload), indent=2, default=str))
    return result


if __name__ == "__main__":
    main()
