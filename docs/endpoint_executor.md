# Endpoint executor

The endpoint executor returns broker-native payloads together with canonical `InternalExecutionProvenance`. It does not resolve payload paths, apply semantic mappings, create semantic records, or construct portfolios.

`RegistryEndpointExecutor` resolves a physical endpoint from its broker registry, validates and applies defaults to parameters, dispatches the declared transport, and records request/response facts that are safe to retain. The raw response remains solely in `ExecutionResult.payload`; provenance never embeds it.

```python
from alertissimo.core.brokers.execution import RegistryEndpointExecutor

result = RegistryEndpointExecutor().call(
    "fink", "ztf", "objects", objectId="ZTF19acmdpyr"
)
print(result.payload)
print(result.execution_provenance)
```

Credentials are transport concerns. Sensitive header values are represented as `<redacted>` in execution provenance.
