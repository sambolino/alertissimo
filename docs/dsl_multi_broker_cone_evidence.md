# C4e — Retrieve all initial classification channels before selection

Branch: `fix/dsl-multi-broker-cone-evidence`.
Base: `964244f` on `integration/discovery-completion`, after merged C4d and its
reported passing CI checkpoint. Keep main-target #329 draft.

## Scientific behavior

```text
objects from ztf via alerce
inside (124.88, -6.02, 5arcsec)
latest 2
with classification via alerce, fink
where (classification@lc_classifier:alerce.best.class = "SNIa" and classification@lc_classifier:alerce.best.probability >= 0.8) or (classification@fink:fink.best.class = "SN candidate" and classification@fink:fink.assessment.sn_vs_all.probability >= 0.8)
```

Establish the declared cone population, obtain the targeted classification at
both brokers, evaluate the complete authored expression, then apply optional
latest. Existing temporal membership still precedes these Gets. Native-only
discovery conditions retain their current realization.

Broker lists, separate requirements and implied Gets from qualified general where
use the existing retrieval operations. Different broker order does not change
scientific outcomes. Named classifiers at different brokers do not conflict just
because their producer names differ.

Every requested source remains required. A failed request is an execution failure;
a successful empty response supplies no assertion. Under OR, an established match
at the other broker may still qualify. AND is not rewritten as OR or a quorum.
The scoped broker-list condition keeps C1's existing meaning: at least one broker
must satisfy the whole scoped condition. `confirm` remains the explicit quorum
operation and is outside this branch's initial-scope work.

Qualified label references can be compared directly with the existing predicate
operators. That compares supplied assertion values literally. It does not invent
a common taxonomy, infer scientific correctness, or equate different score scales.
Use broker-specific label/assessment paths and deliberate criteria as above.

## Existing compiler and material admission

The compiler keeps the original predicate on the initial local Filter and emits
ordinary Gets before it. The existing after_step boundary records that Filter's
actual occurrence, including when several Gets are needed. Predicate grouping,
qualifiers and literals remain intact; initial summary conditions still use C4d's
semantics. Latest ranks the original discovery recency and continuation never
refills a previously selected population.

Material proof inspects the compiler's actual initial IR, ending at the initial
Filter. Only required, projected discovery and classification call outputs count.
Later refinements cannot lend field proof to initial selection. Each reference
must be present in every eligible route of at least one supplying operation.
This is the same all-route guarantee as checking every independent route
combination, without building a Cartesian product or selecting a route.

Model-selection guards are scoped per broker. Several implicit model-specific
Gets at one broker still require a generic material request there, and a named
Get cannot erase another needed model. A generic request at Fink cannot justify
successive conflicting model selections at ALeRCE. Field/channel identity still
belongs to each call; one broker's probability mapping cannot satisfy an unmapped
probability reference at another broker. Existing unsupported/ambiguous retrieval
checks and the offline planner retain their authority.

No new Step, IR field, runtime execution path, provider recipe/mapping or
architecture layer is added. The previous single-broker material proof becomes
an inspection of the already emitted initial scientific operations.

## Remaining scope

Several classification channels are admitted only for one explicit discovery
source. At least one is external to that discovery source; this change does not
rewrite native-only searches. Existing single-external-channel behavior remains.
Unbounded discovery, mixed multisurvey populations, measurement dependencies,
unqualified classification channels, conflicting same-broker model selection and
initial Confirm/Match keep their guards. No catalogue-wide scan or unproven
provider coverage is substituted. C4 and C5-C7 are still not complete.

## Local verification

Preparation uses source review, AST/YAML parsing, whitespace/path and bundle
checks only. No project imports, tests, builds, app runs or provider requests run
in the preparation environment.

The new public replay module covers broker-order/list/explicit/implied/named Get
forms; whole Boolean conditions with independent broker metrics; literal label
comparison; assertion-local provenance and full survivor measurements; scoped-list
OR and explicit cross-broker AND; empty responses versus required-call failure;
summary and temporal composition; serialization/offline replay; latest's actual
Filter boundary; immutable continuation, pinned clock, downstream survivor IDs
and no refill; initial implied retrieval despite a later explicit request; missing
field rejection and per-broker model-erasure guards. The previous blanket
multi-broker discovery deferral now asserts the supported compiled order.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_multi_broker_cone_evidence.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_dsl_mixed_evidence.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_latest_evidence.py \
  tests/test_dsl_temporal_evidence.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-multi-broker-cone-tests.log
```

After green local tests, push, PR and squash into integration. No extra manual CI
checkpoint is requested for this compiler-only extension immediately after C4d's
passing checkpoint. Reassess checkpoint needs for subsequent core/runtime/contract
changes; final CI must validate the eventual integration/main head. No additional
live provider acceptance is requested for this slice. Keep #329 draft.
