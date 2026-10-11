# Alertissimo
*An über broker for transient alert orchestration*

Alertissimo is a provider-neutral orchestration backend for astronomical transient-alert brokers. It separates scientific intent from physical provider APIs, plans broker calls from declarative capabilities, normalizes heterogeneous responses into semantic Portfolios, and preserves workflow/provenance structure across multi-provider execution.

The **0.1.0** release is a dissertation research prototype. Its public interfaces may change during further development. The packaged provider registry currently covers ALeRCE, ANTARES, Fink, and Lasair. The public user-facing language in this release is the Alertissimo DSL; natural-language and visual-block front ends can target the same canonical workflow layer later without changing provider execution semantics.

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

External clients should use the high-level facade rather than assembling parser, planner, execution, and normalization layers themselves:

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

Provider recipes and predicate/selection bindings, physical endpoint contracts,
semantic mappings, the ontology, DSL grammars, and execution safety policy are
package resources. The [recipe runtime guide](docs/recipe_runtime.md) describes
their ownership and the validation/planning boundary. Automatic provider
pagination is bounded by:

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

## UI prototypes

Start the investigation UI with local object-ID/cone demonstrations, a live DSL
editor, result cards, and normalized object Portfolios:

```bash
PYTHONPATH=. python -m streamlit run alertissimo/app_search.py
```

Object-ID and basic cone controls use frozen broker evidence. Submitting a DSL
workflow makes live provider requests; credentials are loaded from the repository
`.env` without overriding environment variables.

For validation and an execution-plan preview without broker calls:

```bash
PYTHONPATH=. python -m streamlit run alertissimo/app_dsl.py
```

The single-object Portfolio demonstration is available through
`alertissimo/app_plot.py`; `alertissimo/ui/app.py` accepts serialized Portfolio
uploads for light-curve viewing. These are separate prototypes, not yet one
integrated application. The [UI overhaul plan](docs/ui_overhaul.md) tracks the
next small branches.

The UI is not exposed as a console command in the 0.1.0 package; the supported
integration boundary is `alertissimo.api`.

## Release package check

Before tagging a release, build and inspect the wheel, compare its declarative
resources with the checkout, and validate/plan cone recipes for all eight
broker/survey pairs from the installed wheel copy:

```bash
PYTHONPATH=. python scripts/check_release_package.py
```

The check is offline with respect to astronomical broker APIs.

## Orchestration smoke scenarios

Offline multi-provider, batch, and expected-failure acceptance commands are documented in [`scripts/smoke/README.md`](scripts/smoke/README.md).

## Citation

If you use Alertissimo in research, please cite the archived version corresponding to the code you used. Citation metadata is provided in [`CITATION.cff`](CITATION.cff), and GitHub exposes it through the **Cite this repository** action. The source repository is available at <https://github.com/sambolino/alertissimo>.

The version-specific Zenodo DOI for the dissertation snapshot will be added after the `v0.1.0` release has been published and archived.
