# Activate bounded Lasair ZTF object-summary discovery

Lasair ZTF can now discover candidates through the existing `semantic_search`
recipe using numeric comparisons on three mapped object-summary fields. Previously
semantic discovery had no Lasair recipe. A required `conditions` assignment now
comes from eligible predicates; an absent or unsupported predicate defers before
binding. This is 05b, based on merged pagination PR #303, main `dd12dd2`.

```text
objects from ztf via lasair
where summary.detection_count >= 5 and summary.time.last_mjd >= 59190 and summary.time.last_mjd < 59200
with lightcurve via lasair
```

Those dates describe a historical **object-summary** interval for the recorded
example. They are not a suggested current live window. The condition selects
objects using their returned current summary; it does not reconstruct which
alerts or classifications were available historically. Downstream lightcurves
retain all returned measurements, including measurements outside that interval.
`summary.detection_count` is the provider-reported count, not a count of locally
loaded detections or a quality-qualified aggregate.

## Exact support

| Contract | Admitted now | Deferred |
| --- | --- | --- |
| Lasair ZTF | Finite numeric `=`, `<`, `<=`, `>`, `>=` on `summary.detection_count`, `summary.time.first_mjd`, `summary.time.last_mjd`; conjunctions; compatible producer/channel qualifiers | Unconstrained discovery, strings/booleans/nonfinite numbers, other fields, identity literals, classification/context joins, OR/NOT, mixed untranslated predicates, generic `within`, `latest`, arbitrary criteria |
| Lasair Rubin | Existing lookup/cone/lightcurve recipes and physical query contract | Semantic SQL discovery: existing query captures establish identity, not a verified full summary/classification projection; ZTF columns and time conversions are not inferred |
| Raw `sql_query` | Existing physical contract remains inspectable | Whole-query lowering remains deferred; the semantic recipe does not parse arbitrary SQL |

`!=` is deliberately deferred: SQL NULL comparisons and the current local
predicate evaluator do not supply an interchangeable missing-value contract.
Literal-left comparisons invert the operator explicitly. Repeated bounds on the
same field form an AND expression; they do not overwrite one physical scalar.
All leaves must translate. This first bounded SQL form does not issue a broad
superset query when an unsupported leaf, qualifier, or boolean form remains.

## Existing boundaries

Provider-local `predicate_bindings` gain an optional `sql` representation with
`column`, optional `subtract`, and `order_by`. These compile into additional
optional fields on the existing `RequestConstraintCapability`. Ordinary scalar
bindings retain their existing conflict rules. Multiple SQL comparisons can share
one conditions parameter only with consistent ordering; duplicate path/operator
bindings remain invalid.

The existing recipe loader verifies qualified identifiers, endpoint output
mappings, mapped identity ordering, and the supported output arithmetic. It admits
only an untransformed column or the already mapped JD-to-MJD subtraction. The SQL
recipe must declare a constant projection containing every bound field and the
identity, one table, and automatic offset pagination. Call output evidence is
restricted to selected fields; adding an unrelated query mapping cannot advertise
unselected material as a discovery output.

The existing predicate planner renders finite numeric literals through the pure
SQL transform helper, preserves comparison operators, and appends stable
`ORDER BY objects.objectId` once. It emits no arbitrary user text. No string
escaping policy is needed for this numeric-only subset: text is rejected rather
than interpolated. The full predicate remains residual for normalized rechecking.
This recheck can remove unexpected returned rows; it cannot recover candidates a
provider omitted.

For example, canonical `summary.time.last_mjd >= 59190` becomes
`(objects.jdmax - 2400000.5) >= 59190`. The subtraction matches the response
mapping directly, avoiding rounding a literal through an inverse conversion to
JD. It is not a new time scale or a historical alert-window interpretation.
Column arithmetic can cost more than an indexed native-JD range; large searches
may be slow or reach existing execution-policy limits.

The binder already accepts realized physical predicate parameters independently
of recipe value-source encoders. The existing target-ID `IN (...)` encoder on
`conditions` remains unchanged for composite cone supplements. There is no
endpoint alias, new IR/DSL operation, dependency, result model, or architecture
layer. Physical endpoint and response mapping files are unchanged in this branch.

The discovery recipe omits explicit offset/limit. It inherits the safe automatic
1000-row page size and existing maximum-page policy from 05a. Full final pages
require an empty probe; policy exhaustion and provider error objects fail
explicitly. Stable ordering avoids arbitrary page order but provides no database
snapshot isolation while objects change between calls. No new completeness or
historical snapshot guarantee is claimed beyond that physical page contract.

## Source and response evidence

Read-only inspection used official
[`lsst-uk/lasair4` `2b940d41`](https://github.com/lsst-uk/lasair4/tree/2b940d41c456545164c587e0f053e6312c2d105a):

- `common/schema/objects.sql` and `objects.py`: primary object identity, integer
  `ncand`, and double `jdmin`/`jdmax`; their descriptions distinguish earliest
  candidate JD and latest band detection JD.
- `webserver/lasair/query_builder.py`: selected/tables/conditions contract,
  arithmetic comparisons and ordering in conditions; physical limit/offset are
  separate parameters.
- `webserver/lasairapi/serializers.py`, `QuerySerializer`: form inputs, native
  LIMIT/OFFSET, account limit clamping, array results and object-shaped errors.

The unchanged ZTF `capture_20260813T110413Z/query_core.json` confirms the six-field
projection and native JD values. The existing Rubin
`capture_20260813T140948Z/query_object_qualified.json` confirms only its identity
projection. Neither capture proves that a deployed service is identical to the
source snapshot, or that changing multi-page populations form a stable snapshot.

## Local verification

No tests, builds, apps, project imports, or broker requests ran here. Python AST,
YAML syntax, whitespace, and bundle checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_lasair_semantic_search.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_sql_recipes.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_orchestration_offset_pagination.py \
  tests/test_dsl_candidate_recipes.py
```

The new suite independently evaluates the generated SQL with SQLite over the
unchanged captured row and explicitly synthetic additional candidates. It covers
numeric operators/units/qualifiers, same-column bounds, plan serialization,
pre-network deferral, projection/mapping validation, pagination before downstream
binding, retention of measurements, normalized rechecking, empty populations,
policy exhaustion, and HTTP-200 error objects. SQLite is an offline fixture
engine, not validation of deployed MySQL behavior. Existing composite-cone
regressions continue to protect the separate target-ID encoder and explicit
bounded supplement. Two older fixture-authoring tests now isolate their cone
recipes from unrelated production semantic-search declarations; their assertions
are retained. The public bare-ZTF-search expectation changes from unsupported to
deferred because the new recipe requires eligible conditions.

DSL CI includes the new facade module once; the other edited suites already run
there. Live validation remains a separate user-run acceptance step with the
existing `LASAIR_ZTF_TOKEN` environment variable. After merge, continue to the
ANTARES provider branch in the integration plan.
