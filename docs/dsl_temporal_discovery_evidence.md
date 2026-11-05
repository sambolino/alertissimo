# C4f — Classification after time-bounded discovery without a cone

Branch: `fix/dsl-temporal-discovery-evidence`.
Base: `8bd28cd` on `integration/discovery-completion`, after merged C4e (#341).
Keep main-target #329 draft.

## Scientific behavior

```text
objects from ztf via alerce
within 7d
with classification via fink where best.class = "SN candidate"
latest 10
```

The existing temporal recipe establishes membership before targeted classification
retrieval. Evaluate the initial condition on that material, then select the latest
matching objects using the original discovery recency. A cone is optional for this
composition when one explicit discovery source has a supported temporal contract.
ALeRCE/ZTF and Lasair/ZTF admit detection, first and last membership through their
existing production recipes. Their provider pagination and required-history proofs
remain authoritative; this change introduces no provider contract or endpoint.

`latest` remains declarative within the initial clauses. Moving it before `with`
or to the end of those clauses emits the same workflow. An explicit later `filter`
continues to select from the already chosen latest population without refilling it.
`latest` after an explicit `filter` remains rejected.

General qualified conditions, scoped requirements, mixed summary/classification
conditions and multiple classification brokers use the same material checks as
C4e. For example, ALeRCE probabilities have class-specific assessment fields:

```text
objects from ztf via alerce
first within 7d
with classification via alerce, fink
where classification@lc_classifier:alerce.assessment.snia.probability >= 0.8 or classification@fink:fink.best.class = "SN candidate"
latest 10
```

The ALeRCE assessment is supplied by `query_probabilities`; it is not a synthesized
`best` classification. Scores and labels retain their producer and channel.
The whole Boolean expression is evaluated after the required material arrives.

## Implementation and limits

Extend the existing compiler scheduling guard from cone discovery to a single
time-bounded SemanticSearchStep. Rename its private helper to describe both cases
and use the same helper in candidate, retrieval-material and latest admission.
Existing SearchSelection.after_step, FilterStep, planner, binder, runtime,
normalization and continuation implement the ordering without modification.

Neither an external classification condition nor `latest` alone authorizes an
unconstrained catalogue scan. Requests without a cone or time context retain
their existing guard. Native-only classification search, mixed discovery sources,
measurement dependencies and initial Confirm/Match are not extended here. A time
context alone cannot invent a missing provider translation, required query seed,
complete history or global recency contract. In particular this slice does not
activate ANTARES time-only discovery, Fink time-only discovery with external
classification, or unsupported Rubin temporal/latest contracts.

Continuation pins the original clock and executed prefix, preserves source
provenance and all survivor measurements, and never restores time-rejected or
previously unselected candidates through history reuse.

## Verification and handoff

Replay the production recipes with synthetic transports; no live calls are needed
for these regressions. Existing temporal and multi-broker fixtures now cover the
same flows with and without a cone: all time modes, relative/absolute windows,
closed boundaries, history gaps, paging, field proof, multiple broker forms,
required-evidence failures, replay/serialization, frozen recency, continuation,
history reuse and no refill. Dedicated cases compare initial latest placements
and distinguish later filtering. Unsupported and unbounded forms fail before
provider calls.

Preparation verification passed 223 distinct offline cases across the nine
modules below, in focused and regression runs. No live provider request or
remote workflow was run during preparation.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_temporal_evidence.py \
  tests/test_dsl_multi_broker_cone_evidence.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_latest_evidence.py \
  tests/test_dsl_mixed_evidence.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_fragments.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-temporal-discovery-evidence-tests.log
```

After green local checks, push, PR and squash into integration. Run a DSL and
semantic-registry checkpoint on the resulting integration head because this
extends the shared scheduling guard to another discovery operation. Live
deployment acceptance and final integration CI remain separate requirements.
C4 is not complete; unrestricted discovery, other dependencies and C5-C7 remain.
