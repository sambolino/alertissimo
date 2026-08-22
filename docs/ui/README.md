# Alertissimo DSL — UI Builder Guide

This document is for the visual DSL builder.

The UI should generate **Alertissimo DSL**, not a parallel query model. Blocks may help the user construct the DSL, but the backend parser/compiler remains the source of truth.

## 1. Three levels of "valid"

A DSL fragment can be:

1. **Lexically valid** — accepted by the parser.
2. **Semantically/capability valid** — ontology references exist and a compatible provider capability is registered.
3. **Runnable** — it compiles to IR and the planner can produce an executable workflow.

Do not treat lexical validity as proof that something can run.

For the normal UI, prefer blocks known to compile and use capability validation to enable/disable provider-specific choices.

---

## 2. Basic structure

Every workflow begins with a candidate population:

```text
objects from ztf
```

```text
objects from lsst, ztf via alerce
```

`from` here means **data origin/survey**.

`via` means **broker/provider**.

After that, clauses are added in order:

```text
objects from ztf via alerce
inside (124.87996, -6.02050, 1arcsec)
latest 10
with lightcurve via fink
filter classification@fink.best.probability >= 0.5
```

Order matters because later clauses may operate on material produced by earlier clauses.

---

## 3. Recommended UI blocks

These are the main blocks that should currently be exposed.

| Block | DSL |
|---|---|
| Candidate origin | `objects from ztf` |
| Multiple origins | `objects from lsst, ztf` |
| Discovery broker | `via alerce` |
| Sky cone | `inside (RA, DEC, 5arcsec)` |
| Time window | `within 7d` |
| Latest N | `latest 10` |
| Search predicate | `where <expression>` |
| Local filtering | `filter <expression>` |
| Retrieve product | `with <product> via <broker>` |
| Match candidates | `match on position inside 1arcsec` |
| Result ordering | `order by <expression> [asc\|desc]` |

Angles should always be emitted with explicit units:

```text
1arcsec
2arcmin
0.5deg
```

Although an angle without a unit can parse, it cannot currently be lowered safely.

---

## 4. Common runnable formulations

### Search

```text
objects from ztf via alerce
inside (124.87996, -6.02050, 5arcsec)
latest 10
```

### Search and enrich

```text
objects from ztf via lasair
inside (124.87996, -6.02050, 5arcsec)
latest 1
with lightcurve via fink
with lightcurve via alerce
```

Multiple `with` clauses accumulate semantic material for the same candidate objects.

### Cross-broker enrichment

```text
objects from ztf via fink
inside (124.87996, -6.02050, 1arcsec)
latest 1
with lightcurve via alerce
with crossmatch via antares
```

### Multi-origin positional Match

```text
objects from lsst, ztf via alerce
inside (150.124522, 0.877582, 300arcsec)
match on position inside 1arcsec
```

Match filters the candidate population to objects participating in a successful relation.

### Match followed by enrichment

```text
objects from lsst, ztf via alerce
inside (150.124522, 0.877582, 300arcsec)
match on position inside 1arcsec
with lightcurve via fink
```

Only Match survivors are passed to the downstream retrieval.

---

## 5. Predicates

Predicate syntax supports:

```text
=
!=
>
<
>=
<=
and
or
not
exists
(...)
```

Examples:

```text
classification@fink.best.probability >= 0.5
```

```text
classification@fink.best.class = "SN"
and classification@fink.best.probability >= 0.5
```

```text
exists crossmatch@gaia_dr1
```

References follow approximately:

```text
record_type.field
record_type@producer.field
record_type@producer:channel.field
```

The UI should preferably suggest semantic paths from the ontology rather than allowing users to invent them blindly.

---

## 6. `with` syntax

General lexical form:

```text
with PRODUCT [from PRODUCER] [via BROKER] [using METHOD]
```

Examples:

```text
with lightcurve via fink
```

```text
with classification from stamp_classifier_rubin_beta_20260421
```

```text
with crossmatch from gaia_dr3
```

There are also scoped predicates:

```text
with classification from stamp_classifier_rubin_beta_20260421:
    best.class = "SN"
    best.probability >= 0.5
```

The indented predicates are implicitly conjunctive.

### Important: `from` is contextual

Do **not** model every `from` block as the same concept.

```text
objects from ztf
```

Here `from ztf` means **candidate origin**.

```text
with classification from classifier_x
```

Here it means **classification producer**.

```text
with crossmatch from gaia_dr3
```

Here it means **catalog/source of the crossmatch**.

Therefore this is **not** the way to select ZTF objects:

```text
with lightcurve from ztf via fink
```

Candidate origins are established by the initial `objects from ...` statement.

The visual builder should therefore use different internal block types even though they render the same word `from`.

---

## 7. Lexically accepted but not necessarily runnable

The parser intentionally accepts a slightly wider language than the currently executable subset.

Examples include:

```text
ranked by ...
```

This currently parses but canonical ranking semantics are deferred, so compilation rejects it.

Similarly, these products exist in the DSL/IR vocabulary but should only be offered when capability validation says the requested origin/broker combination is supported:

```text
with classification ...
with crossmatch ...
with lightcurve ...
with forced_photometry ...
with cutout ...
with spectrum ...
with data_product ...
```

Do not maintain a second hard-coded provider matrix in the UI.

Ask the backend capability graph.

`order by`, unlike `ranked by`, is result-view intent rather than a scientific workflow Step.

---

## 8. Validation available to the UI

Validation can be performed without contacting provider APIs.

Recommended sequence:

```python
from alertissimo.dsl import (
    DSLParseError,
    SurfaceLoweringError,
    compile_surface,
    parse_surface_script,
    validate_surface_capabilities,
    validate_surface_semantics,
)
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.orchestration.planner import plan_workflow

graph = build_capability_graph()

surface = parse_surface_script(text)

semantic_report = validate_surface_semantics(surface)

if semantic_report.is_valid:
    capability_report = validate_surface_capabilities(
        surface,
        graph=graph,
    )

    compilation = compile_surface(
        surface,
        graph=graph,
    )

    run = plan_workflow(compilation.workflow, graph)
```

The UI can expose validation progressively:

### Syntax validation

`parse_surface_script()`

Catches malformed DSL and provides line/column information.

Use while editing.

### Ontology validation

`validate_surface_semantics()`

Checks semantic products, references and paths.

Returns structured issues containing:

```text
severity
code
message
clause_index
```

Good for marking an individual block red/yellow.

### Capability validation

`validate_surface_capabilities()`

Returns structured checks with statuses:

```text
supported
unsupported
deferred
not_applicable
```

Checks may also contain provider/origin/endpoint evidence.

This is the best source for context-sensitive block suggestions.

For example, after:

```text
objects from ztf
```

the UI can ask which brokers/products are currently supported rather than maintaining its own table.

### Compilation validation

`compile_surface()`

Tests whether valid surface intent can currently be represented faithfully in canonical IR.

`SurfaceLoweringError` exposes a machine-readable:

```text
code
clause_index
```

For example a construct may be perfectly legal DSL but currently have deferred downstream semantics.

### Planning validation

`plan_workflow()`

Final non-network validation: verifies that the compiled semantic Steps can actually be mapped to physical endpoint plans.

---

## 9. Suggested UI behavior

Use two sources of suggestions:

```text
formal grammar
      ↓
which blocks/tokens may occur here

ontology + capability graph
      ↓
which semantic values/providers make sense here
```

A useful visual state model is:

```text
gray    incomplete block
green   valid + supported
yellow  valid but deferred / not currently executable
red     syntax, ontology or unsupported-capability error
```

Do not expose endpoint names or physical request parameters in the normal DSL builder. Those belong to planning/execution, not user semantic intent.

The generated text remains the authoritative representation and should always be editable directly.
