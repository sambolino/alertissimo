# Alertissimo DSL — UI builder guide

Generate the existing DSL and validate it through the backend. Blocks are editing
aids; canonical WorkflowIR, ontology and capabilities own scientific meaning.
Keep the generated text visible and editable. Do not maintain another provider
matrix, query model or executor in the UI.

## Validation levels

1. Parsing accepts the surface syntax.
2. Semantic/capability checks establish known references and admitted operations.
3. Lowering and offline planning establish a runnable physical workflow.

None proves provider availability or successful execution. Prefer the public
facade, which composes these checks without provider calls:

```python
from alertissimo.api import validate_dsl
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph

graph = build_capability_graph()
validation = validate_dsl(text, graph=graph, continue_from=None)
# Inspect is_valid, is_runnable, parse_error and lowering_error.
```

Use the same visible parent execution for validation and execution of a fragment.
Explicit `None` requires a complete fresh program; an explicit `DSLExecutionResult`
continues that result. Omitted `continue_from` retains compatibility active state
and is unsuitable for selecting a UI editor's parent. Failures retain the last
successful view; replacing a parent clears old descendant results.

Low-level parser, semantic/capability reports and compiler diagnostics remain
available for block feedback. `validate_surface_semantics` reports severity, code,
message and clause index; capability checks distinguish supported, unsupported,
deferred and not_applicable with source evidence. `SurfaceLoweringError` retains
code/clause metadata. Suggest providers/fields from those owners, not endpoint
names or physical parameters.

## Candidate population and clauses

`from` on the initial candidate statement means survey; `via` means broker:

```text
objects from lsst, ztf via alerce
inside (150.124522, 0.877582, 300arcsec)
match on position inside 1arcsec
with lightcurve via fink
```

Match retains candidates participating in a successful relation; only survivors
feed later retrievals. Named lookup uses the same canonical pipeline:

```text
object ZTF21abfmbix from ztf via alerce
with classification via alerce
```

Lookup does not admit initial inside/within/latest. Continuation cannot change the
initial population or its constraints; use later `filter` and retrieval clauses.

| Intent | Surface form |
| --- | --- |
| Spatial selection | `inside (RA, DEC, 5arcsec)` |
| Temporal selection | `within 7d`, `first within 7d`, `last within 7d` |
| Global latest | `latest 10` |
| Initial condition | `where <expression>` |
| Later candidate refinement | `filter <expression>` |
| Material | `with <record noun> via <broker>` |
| Matching | `match on position inside 1arcsec` |
| Display ordering | `order by <expression> [asc\|desc]` |

Emit explicit angle units (`arcsec`, `arcmin`, `deg`). Unitless angles may parse
but do not lower safely. Temporal/latest admission differs by route; consult the
[discovery matrix](../discovery_integration.md). In particular, Fink cone latest
is deferred. `order by` is display intent, not a candidate-selection Step.

```text
objects from ztf via alerce
inside (124.87996, -6.02050, 1arcsec)
latest 10
with classification via fink
filter classification@fink:fink.assessment.sn_vs_all.probability >= 0.5
```

Here the explicit later filter refines the selected latest population and never
refills it. An initial `where` instead precedes global latest evaluation, even
when required evidence must first be retrieved. Its placement among initial
clauses is declarative; `where`/inside/within/latest after an explicit `filter`
are rejected. Unbounded or unproven evidence dependencies defer before calls.

Multiple retrievals accumulate material for each candidate:

```text
objects from ztf via lasair
inside (124.87996, -6.02050, 5arcsec)
latest 1
with lightcurve via fink
with lightcurve via alerce
```

## Predicates and qualifications

Comparisons are `=`, `!=`, `>`, `<`, `>=`, `<=`; combine them with AND, OR, NOT,
exists and parentheses. Keywords are case-insensitive. Indentation is cosmetic;
newlines and a trailing colon do not imply grouping, scope or AND.

```text
classification@fink:fink.best.class = "SN candidate" AND classification@fink:fink.assessment.sn_vs_all.probability >= 0.5
```

References have the forms `record.field`, `record@producer.field`, and
`record@producer:channel.field`. A measurement producer is normally the survey;
a classification producer is its method, not automatically a survey or broker.
Suggest actual mapped fields: Fink's named probabilities are not a generic
`best.probability`. Unknown evidence stays unknown under NOT. Class/metric
conditions on one selector require one assertion witness; qualification does not
calibrate different methods. Candidate filtering retains other survivor evidence.

## Material requirements

The lexical form is:

```text
with PRODUCT [from PRODUCER] [via BROKER] [using METHOD]
```

Products must be Portfolio record nouns or admitted family members. Typical
retrieval nouns are classification, crossmatch, lightcurve and data_product.
Recognition alone is not retrieval support. `with measurement` has no current
retrieval lowering; `with forced_photometry` and `with cutout` fail the current
Portfolio noun gate, despite programmatic IR operations. A cutout is a data_product
type, not a new request noun. Spectrum requires an actual admitted retrieval.

`with enrichment` expands to supported concrete Gets using the supplied graph;
unsupported/deferred members do not become enabled. Family-wide predicates and
producer/method restrictions are rejected rather than copied onto unlike children.
See [architecture](../../ARCHITECTURE.md) for family and required-call rules.

`from` in a requirement is contextual: classifier for classification, catalogue
for crossmatch. It never changes the candidate survey. Therefore
`with lightcurve from ztf via fink` does not select ZTF candidates.

A scoped condition occupies the same physical line as its requirement:

```text
object 170587117485817955 from lsst via alerce
with classification from stamp_classifier_rubin_beta_20260421 where best.class = "SN" AND best.probability >= 0.5
```

Do not emit Python-like `with ...:` blocks or indent a separate `where` to imply
scope. A general initial `where` may occur before or after initial requirements;
its scope ends at a later refinement boundary.

Only classification currently accepts a retrieval broker list:

```text
object ZTF21abfmbix from ztf via alerce
with classification via alerce, fink
```

The list requests each broker's material; it is not quorum. An inline condition
is scoped wholly to one listed broker at a time and those alternatives are ORed.
A class at one broker and score at another cannot jointly witness that condition.
Explicitly qualified references retain their qualifiers. Duplicate brokers fail;
unavailable/ambiguous members are not silently dropped. Use Confirm for quorum.
A `from` model applies to every listed broker; it does not define model aliases.

## Deferred syntax and future work

`ranked by` parses but canonical ranking remains deferred. Unsupported selectors,
local construction methods or products must remain visibly deferred/unsupported;
parsing is not execution support. Collection aggregates/quantifiers and optional
element bindings follow the [collection contract](../dsl_collections.md); do not
advertise them as implemented or infer grouping from indentation.

Use grammar for possible next blocks and ontology/capability evidence for legal
values. Show incomplete, supported, deferred and rejected states distinctly.
Physical calls and detailed planning evidence belong in expandable technical
views, not ordinary scientific controls.
