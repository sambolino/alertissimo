# C4d — Whole summary/classification predicates after required evidence

Branch: `fix/dsl-mixed-cone-predicates`.
Base: `91f350c` on `integration/discovery-completion`, after C4c (#339).
Keep main-target #329 draft.

## Scientific behavior

```text
objects from ztf via alerce
inside (124.88, -6.02, 5arcsec)
latest 2
with classification via fink
where summary@ztf:alerce.detection_count <= 2 or (classification@fink:fink.best.class = "SN candidate" and classification@fink:fink.assessment.sn_vs_all.probability >= 0.8)
```

A scoped inline condition is also supported, for example:

```text
with classification via fink where summary@ztf:alerce.detection_count >= 5 and best.class = "SN candidate"
```

For this bounded, single-source cone population, discover first, retrieve the
external classification, evaluate the complete original condition, then apply
optional latest. Do not push one side of the mixed OR into discovery: it would
discard candidates that satisfy only the other side. This branch also keeps
mixed AND/NOT expressions whole, including grouping, qualifiers and literals.
There is no Boolean distribution, implicit quorum or partial native pruning.

Class and probability/score references with the same selector still bind to one
assertion. An SN/low-probability assertion and a separate AGN/high-probability
assertion cannot satisfy an SN/high-probability conjunction. Missing values stay
unknown under NOT; they do not become established negative evidence.

Qualifications keep their existing meaning. `summary@ztf:alerce.detection_count`
asks for that source's summary. Unqualified `summary.detection_count` retains the
existing evaluator's matching-record semantics over the acquired material; a
Fink summary can satisfy it too. No implicit source preference is added. Use a
qualified reference when the distinction matters. Displayed reported counts
remain separate from loaded measurement counts.

## Evidence proof and architecture

Existing discovery and targeted retrieval capability checks identify eligible
routes. The compiler inspects the required call outputs of each eligible route,
respecting constant projections and excluding supplementary calls. Each referenced
field must be mapped by the combined discovery/retrieval material for every
eligible route combination. A mapping elsewhere in the graph cannot establish
that the authored calls request that field. Dynamic projections do not provide
static field proof. This inspection does not choose an endpoint or run a request.

The shared mapped-field matcher now uses each field's own broker when a legacy
record type omits its channel suffix. A union of fields from different calls
cannot borrow the retrieval broker's identity for another call's legacy record.
Producer, channel and dynamic path checks remain intact.

An optional Lasair cone summary cannot establish a required summary condition.
Its existing latest/temporal recipe can provide the summary because that call is
required. The summary projection must still contain the requested field. Mapped
availability does not guarantee a value on every object; absent values retain
the existing unknown evaluation policy.

Operations remain ConeSearchStep → existing Gets → FilterStep. C4b's after_step
boundary applies latest after that Filter; C4c's membership proof runs before
targeted retrieval. Time, ranking, snapshots, full survivor material, downstream
binding and no-refill continuation use the existing paths. No new IR field,
provider mapping/recipe, runtime path or architecture layer is introduced.

## Remaining scope

This adds summary references only to the C4 external classification path, for one
explicit discovery source and one external classification channel. Summary
references may be unqualified or name those acquired source channels. Existing
native summary-only searches retain their behavior. Mixed multisurvey discovery,
several classification channels, unbounded dependency scheduling, measurement
dependencies, initial Confirm/Match and conflicting model selections remain
guarded. C4 and C5-C7 are not complete; classification endpoint search stays last.

## Verification and handoff

Preparation uses source review, AST/YAML parsing, whitespace/path and bundle
checks. No project imports, tests, builds, applications or provider requests run
in the preparation environment.

The new public replay module covers mixed AND/OR/NOT with where before/after with,
inline scoping, assertion correlation, missing evidence, qualified/unqualified
summaries, complete predicate serialization, full survivor measurements, deferred
latest and no-refill continuation, equivalence to an explicit continuation filter,
existing temporal composition, required composite summary material, optional and
unprojected field rejection, and legacy broker attribution. Broader dependencies
remain rejected before transport. The module is in DSL's existing wildcard and
explicitly in registry CI. The former blanket mixed-predicate deferral regression
is replaced by this positive/negative coverage; unbounded and Confirm guards stay.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_mixed_evidence.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_latest_evidence.py \
  tests/test_dsl_temporal_evidence.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_classification_material.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-mixed-cone-predicates-tests.log
```

After green local tests, push, PR and squash into integration. The shared field
matcher and material admission proof change, so run one manual DSL/registry
checkpoint on the merged integration SHA before expanding further:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
```

No extra live provider acceptance is requested here. Keep #329 draft; final
main-target checks must still validate the eventual head.

## C4e follow-up

C4d merged as `964244f`, and the operator reported its CI checkpoint passed.
[C4e](dsl_multi_broker_cone_evidence.md) prepares several classification channels
in the same bounded cone, superseding the single-classification-channel guard
above. Per-broker model guards and required projected material remain essential;
this is not a new consensus or cross-survey identity policy.
