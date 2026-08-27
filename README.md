# Alertissimo
*An über broker for transient alert orchestration*

Alertissimo is a provider-neutral orchestration backend for astronomical transient-alert brokers. It separates scientific intent from physical provider APIs, plans broker calls from declarative capabilities, normalizes heterogeneous responses into semantic Portfolios, and preserves workflow/provenance structure across multi-provider execution.

The **0.9.0** line is a backend beta. The packaged provider registry currently covers ALeRCE, ANTARES, Fink, and Lasair. The public user-facing language in this release is the Alertissimo DSL; natural-language and visual-block front ends can target the same canonical workflow layer later without changing provider execution semantics.

## Install

From a source checkout:

```bash
python -m pip install .
```

For development:

```bash
python -m pip install -r requirements.txt
```

Alertissimo requires Python 3.10 or newer.

## Public Python API

External clients should use the stable high-level facade rather than assembling parser, planner, execution, and normalization layers themselves:

```python
from alertissimo.api import validate_dsl, execute_dsl

source = """objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 1arcsec)
latest 1
with lightcurve via fink
"""

validation = validate_dsl(source)   # no provider API calls
if validation.is_runnable:
    result = execute_dsl(source)    # real provider execution
```

`execute_dsl()` returns the finalized semantic workflow result and browser-safe serialization helpers while keeping raw provider payloads behind the execution boundary.

## Declarative runtime

Provider endpoint contracts, request mappings, semantic mappings, the ontology, DSL grammars, and physical execution safety policy are package resources rather than hard-coded application choices. Automatic provider pagination is bounded by:

```text
alertissimo/data_layer/execution/policy.yaml
```

Reaching that physical safety limit raises an explicit error; Alertissimo does not silently truncate scientific results.

## DSL examples

The best single collection of end-to-end runnable DSL examples is:

```text
scripts/live_dsl_facade_acceptance.py
```

The formal grammar is in:

```text
alertissimo/dsl/grammar.lark
```

## UI prototype

The repository still contains the current Streamlit DSL validation/compilation prototype:

```bash
python -m streamlit run alertissimo/app_dsl.py
```

It is not exposed as a console command in the 0.9.0 package; the supported integration boundary is `alertissimo.api`.

Natural-language entry page (uses the local Ollama QLoRA model and then the
same DSL execution flow as the search page):

```bash
python -m streamlit run alertissimo/app_nlp_search.py
```

## Local Qwen3 QLoRA model

Instructions for installing Ollama, creating the fine-tuned local model,
evaluating it, and sharing it with colleagues are in
[`docs/ollama_qlora.md`](docs/ollama_qlora.md).

## Release package check

Before tagging a release, build and inspect the wheel and run static DSL validation from the installed wheel copy:

```bash
PYTHONPATH=. python scripts/check_release_package.py
```

The check is offline with respect to astronomical broker APIs.

## Orchestration smoke scenarios

Offline multi-provider, batch, and expected-failure acceptance commands are documented in [`scripts/smoke/README.md`](scripts/smoke/README.md).
