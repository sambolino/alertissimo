# Endpoint executor

The endpoint executor is the physical I/O boundary between a logical broker
endpoint call and a broker-native payload. It loads three existing registry
views:

- `endpoints.yaml` supplies physical methods, paths, parameters, and transport
  kinds.
- `mappings.yaml` supplies the payload roots and semantic paths produced by an
  endpoint. These are registry metadata only; the executor does not apply the
  mappings.
- `capabilities.yaml` supplies the existing broker-level capability inventory.

The executor validates physical parameters, selects a configured transport,
measures the call, and generates an `InternalExecutionId`. It deliberately does
not resolve payload paths, transform fields, build semantic records, or create
portfolio/provenance objects.

## Direct API

```python
from alertissimo.core.brokers.execution import (
    EndpointRegistry,
    FixtureTransport,
    RegistryEndpointExecutor,
)

fixtures = FixtureTransport({
    ("lasair", "ztf", "object"): {
        "objectId": "ZTF25aazqavg",
        "candidates": [],
    },
})
executor = RegistryEndpointExecutor(
    EndpointRegistry(),
    transports={"rest": fixtures},
)
result = executor.call(
    broker="lasair",
    origin="ztf",
    endpoint="object",
    params={"objectId": "ZTF25aazqavg"},
)

assert result.payload["objectId"] == "ZTF25aazqavg"
assert str(result.internal_execution_id).startswith("exec_")
```

`FixtureTransport` can be registered under `rest` and/or `python` during tests.
`RestTransport` executes public GET/POST endpoints and decodes broker JSON
without applying semantic mappings. Credential resolution and a real
Python-client transport remain later steps.

## Temporary command examples

There is no new DSL parser in this layer. Until a future DSL/planner produces
structured endpoint calls, `execution.examples` recognizes only three exact,
hardcoded demonstrations:

```python
from alertissimo.core.brokers.execution.examples import (
    build_example_executor,
    execute_example_command,
)

executor = build_example_executor()
result = execute_example_command("get ZTF19acmdpyr from fink ztf", executor)
print(result.payload)
# [{"i:objectId": "ZTF19acmdpyr", "i:candid": 1}]
```

The other examples are:

```text
get ZTF25aazqavg from lasair ztf
get ZTF25aazqavg from antares ztf
```

Each example also has a directly executable module:

```bash
python -m alertissimo.core.brokers.execution.examples.get_ZTF19acmdpyr_from_fink_ztf
python -m alertissimo.core.brokers.execution.examples.get_ZTF25aazqavg_from_lasair_ztf
python -m alertissimo.core.brokers.execution.examples.get_ZTF25aazqavg_from_antares_ztf
```

`get_ZTF19acmdpyr_from_fink_ztf` calls the real public Fink/ZTF server for the
object `ZTF19acmdpyr` and requests four columns so that it returns a compact,
non-empty JSON response. `get_ZTF25aazqavg_from_antares_ztf` uses the official
ANTARES Python client and prints a JSON view of the returned `Locus` while
preserving that original object in `ExecutionResult.payload`.
`get_ZTF25aazqavg_from_lasair_ztf` calls the authenticated Lasair REST endpoint;
it resolves `LASAIR_ZTF_TOKEN` first from the environment and then from
`.streamlit/secrets.toml`, and redacts the authorization header in metadata.

Each module exposes a `run()` function that returns the complete
`ExecutionResult`. Its `main()` function prints that response when the module is
executed and returns the same object when called from Python:

```python
from alertissimo.core.brokers.execution.examples.get_ZTF25aazqavg_from_lasair_ztf import run

response = run()
print(response.payload)
print(response.internal_execution_id)
print(response.metadata)
```

The adapter is intentionally isolated in the `examples` package; replacing it
with the real DSL will not require changes to `EndpointExecutor` or transports.
