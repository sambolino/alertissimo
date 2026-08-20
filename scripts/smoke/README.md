# Complex orchestration smoke scenarios

These Python-created `WorkflowIR` acceptance fixtures exercise capability planning,
declarative registry binding, runtime execution, normalization, and Portfolio
reporting. `multi-provider` uses the coherent ZTF target `ZTF18abbuksn`, fans
lightcurve retrieval out to Fink and Lasair, and retrieves ALeRCE/ZTF forced
photometry and a lightcurve. `multi-target` sends two IDs through the Fink CSV
object endpoint and Lasair plural lightcurve endpoint.
`partial-failure` verifies the current fail-fast exception preserves earlier and
in-step successes.

```bash
PYTHONPATH=. python -m scripts.smoke --list
PYTHONPATH=. python -m scripts.smoke multi-provider
PYTHONPATH=. python -m scripts.smoke multi-target
PYTHONPATH=. python -m scripts.smoke partial-failure
PYTHONPATH=. python -m scripts.smoke multi-provider --json
PYTHONPATH=. python -m scripts.smoke multi-provider --html-dir /tmp/alertissimo-multi-provider
PYTHONPATH=. python -m scripts.smoke multi-target --html-dir /tmp/alertissimo-multi-target
```

Fixture mode is always the default and performs no network access. `--live` is an
explicit opt-in for the two successful scenarios and uses `EndpointRegistry` plus
`RegistryEndpointExecutor` and existing environment authentication. Output never
contains credentials, authorization headers, or raw payloads. Do not use `--live`
in automated tests. Fixture payload IDs are fixed, so `--target` is rejected
unless `--live` is also supplied; repeat `--target` for a live batch override.
The expected `partial-failure` scenario is always fixture-only.

## Live setup and commands

Install the project and its local development dependency from the repository
root (using a virtual environment is recommended):

```bash
python -m pip install -e .
python -m pip install pytest
```

Create a `.env` file containing the **raw** Lasair token, without the `Token `
prefix. The CLI adds that prefix from the physical endpoint contract. Exported
environment variables take precedence over values in `.env`.

```dotenv
LASAIR_ZTF_TOKEN=your-raw-lasair-token
# Only needed for workflows that call Lasair LSST endpoints:
LASAIR_LSST_TOKEN=your-raw-lasair-lsst-token
```

Run live smoke scenarios with:

```bash
python -m scripts.smoke multi-provider --live
python -m scripts.smoke multi-provider --live --json
python -m scripts.smoke multi-target --live --target ID1 --target ID2
python -m scripts.smoke multi-target --live \
  --target ZTF21abfmbix --target ZTF20acpwljl \
  --html-dir /tmp/alertissimo-multi-target
```

`--html-dir` writes a separate portfolio view for every normalized Portfolio plus an
`index.html` linking them; provider and target results are never combined. The
directory must be missing or empty, and the command never deletes existing
output or opens a browser. Open the generated index yourself if desired:

```bash
xdg-open /tmp/alertissimo-multi-target/index.html
```

It can also be combined with `--json`. In that mode JSON remains the only stdout
content and the generated index notice is written to stderr.

**Warning:** live execution performs real requests against provider services.
Never use the live commands in automated tests. Fixture commands above remain
fully offline and require no credentials.

Lasair POST body encoding is a physical endpoint transport contract (`form`),
not orchestration or semantic workflow behavior. Other REST POST endpoints keep
the transport's backward-compatible JSON default.

Steps remain independent: they cannot consume earlier normalized outputs because
workflow context, dependencies, and step-output references are deferred. These
scenarios are intended to become acceptance fixtures for a later DSL compiler;
they do not introduce DSL v0.1 or workflow parsing.

Lasair lightcurve payloads are safely partitioned by their root `objectId`, but
that `root_field` partition value is not retained in the normalized `Portfolio`.
Reports therefore mark Lasair Portfolio object identity as unavailable rather
than claiming it was verified. Retaining this identity is a prerequisite for the
next workflow-context/dependency PR; this smoke PR does not add a Portfolio field.
