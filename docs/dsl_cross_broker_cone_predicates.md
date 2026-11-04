# C4a — Retrieve classification before pruning a bounded cone

Branch: `fix/dsl-cross-broker-cone-predicates`.
Base: `4b2cc07` on `integration/discovery-completion`, after merged C3a.
Target: integration; keep main-target #329 draft.

## Supported first slice

```text
objects from ztf via alerce
inside (124.87996115142856, -6.0205001, 5arcsec)
with classification via fink
where classification@fink:fink.best.class = "SN candidate"
```

An inline `with classification via fink where best.class = "SN candidate"`
expresses the same condition. A qualified general `where` can also precede the
requirement or imply the existing classification Get when it is absent.

For an explicitly broker-bound cone without a time window or latest selector,
whose entire initial predicate references classification at one other broker,
lower existing scientific operations in this order:

1. ConeSearchStep establishes the declared spatial population.
2. Existing target-bound Gets retrieve requested material for that population.
3. FilterStep evaluates the complete original predicate on the accumulated view.
4. Later explicit filters/retrievals consume only the survivors.

This removes the previous deferral for this bounded case. The scientist need not
rewrite an initial condition as an extra continuation filter. All predicate
nodes, grouping, qualifiers and literals survive in canonical IR; the discovery
Step does not evaluate an external broker's condition against its own response.
The caller can inspect the Get and initial Filter in the compiled workflow.

Exact explicit requirements still suppress redundant implied retrievals; a
generic explicit classification Get can supply a qualified model predicate.
Only initial explicit requirements suppress an implied initial retrieval: a
request after an explicit filter cannot delay evidence needed by that filter.
An OR inside one broker's condition stays intact rather than becoming several
partial discovery requests. There is no hidden quorum or label translation.
All survivor measurements and other material remain available.

## Admission and safety

The compiler chooses lifecycle order from semantic source constraints, not
endpoint names. Existing capability validation checks the discovery operation
and each retrieval. The moved predicate additionally requires mapped field
evidence from every eligible targeted retrieval recipe. A missing mapped Fink
`best.probability`, for example, defers before any provider call rather than
silently filtering the population to empty.

The call-scoped field matcher is shared with the existing discovery-residual
guard, preserving producer/channel checks, dynamic field segments and compiled
projection boundaries. No provider-specific planner branch or new architecture
layer is introduced. No IR fields, endpoint contracts, mappings or recipe schema
fields change. Mapping availability is not a promise that each candidate has a
value: successful empty/missing assertions still follow the existing evaluator.

The spatial population and native coverage limits are those of the existing
declared cone operation. No unbounded catalogue scan or broader class-stream
population is substituted, and no new completeness claim is made.

General `where` is now syntactically allowed after initial `with` clauses for
discovery too. Its position before the first explicit filter preserves initial
scope. Native cases retain their original SearchStep predicate; unsupported
scheduling cases retain their existing capability/planning deferral. General
where/inside/within/latest after an explicit filter remain rejected.

## Deliberately remaining C4 work

This is C4a, not completion of the full C4 milestone. Keep guards for:

- `latest` or temporal selection combined with later classification evidence;
- predicate-defined discovery without a bounding cone;
- mixed discovery-owned and retrieval-owned predicate references;
- conditions spanning several broker channels;
- initial Confirm/Match scope, pending C5;
- conflicting named-model retrievals that could select away needed evidence.

Several producer qualifiers within one broker require an explicit generic material
request for this first slice, avoiding successive implicit model selections.
Specific model requests must agree with all producer references in the condition.
The existing classification retrieval and mapping checks still apply.

Do not move latest ahead of the initial Filter or append a filter after an
already consumed latest-N population. The next C4 branch must apply latest after
required material and predicates, using the discovery recency contract rather
than enrichment-derived recency. Continuation must retain the original selection
and reference clock without refilling earlier latest results.

## Local verification

Preparation used source review, static AST parsing, whitespace, path and bundle
verification only. No project imports, tests, builds, applications or provider
requests ran here.

Regressions extend the existing public replay module: scoped/general clauses
before or after retrieval, complete initial filtering, OR/existence grouping,
preserved discovery/retrieval snapshots, immutable continuation, downstream IDs,
unmapped field rejection and retained latest/time/unbounded/mixed/Confirm guards.
Existing parser tests now verify general where after with is preserved. Shared
predicate correlation, mapping/projection and provider suites remain in the local
check list. No additional live provider acceptance is requested for this slice.

The first local run reported 374 passed and one stale parser expectation. Its
correction checks that a newline `where` remains a separate general clause,
including with cosmetic indentation, while the preceding requirement has no
scoped predicates. It preserves the condition verbatim rather than inheriting
the preceding requirement's classifier. The adjacent inline predicate test
continues to check the scoped form. This correction changes tests only.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_surface.py \
  tests/test_dsl_formal_grammar.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_dsl_confirm.py \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_api_continuation.py \
  tests/test_alerce_semantic_search.py \
  tests/test_fink_semantic_search.py \
  tests/test_lasair_semantic_search.py \
  tests/test_orchestration_sql_time_bindings.py \
  2>&1 | tee /tmp/alertissimo-cross-broker-cone-predicates-tests.log
```

After local success, push and squash into integration. This changes shared
compiler/admission paths, so run one manual DSL/registry checkpoint on the merged
integration SHA before expanding the scheduling scope:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
```

Keep #329 draft. Final main-target checks remain separate and must validate the
eventual head, not a previous checkpoint or skipped draft job.
