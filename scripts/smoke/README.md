# Complex orchestration smoke scenarios

These Python-created `WorkflowIR` acceptance fixtures exercise capability planning,
declarative registry binding, runtime execution, normalization, and Portfolio
reporting. `multi-provider` fans lightcurve retrieval out to Fink and Lasair and
also retrieves ALeRCE forced photometry and an ALeRCE lightcurve. `multi-target` sends two
IDs through the Fink CSV object endpoint and Lasair plural lightcurve endpoint.
`partial-failure` verifies the current fail-fast exception preserves earlier and
in-step successes.

```bash
PYTHONPATH=. python -m scripts.smoke --list
PYTHONPATH=. python -m scripts.smoke multi-provider
PYTHONPATH=. python -m scripts.smoke multi-target
PYTHONPATH=. python -m scripts.smoke partial-failure
PYTHONPATH=. python -m scripts.smoke multi-provider --json
```

Fixture mode is always the default and performs no network access. `--live` is an
explicit opt-in for the two successful scenarios and uses `EndpointRegistry` plus
`RegistryEndpointExecutor` and existing environment authentication. Output never
contains credentials, authorization headers, or raw payloads. Do not use `--live`
in automated tests. The default IDs are chosen for deterministic fixtures; use
repeatable `--target` options when appropriate for live retrieval.

Steps remain independent: they cannot consume earlier normalized outputs because
workflow context, dependencies, and step-output references are deferred. These
scenarios are intended to become acceptance fixtures for a later DSL compiler;
they do not introduce DSL v0.1 or workflow parsing.
