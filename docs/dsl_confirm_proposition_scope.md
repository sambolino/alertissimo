# C5 — Stable confirmation proposition scope

Branch: `fix/dsl-confirm-proposition-scope`.
Base: `e2be63c` on `integration/discovery-completion`, after C4f (#342).
Keep main-target #329 draft.

## Behavior

```text
objects ZTF21abfmbix, ZTF20acpwljl from ztf via alerce
where exists classification.best.class
with lightcurve via fink
confirm by 2 via fink, lasair
```

The confirmation question is whether each candidate has a class label in each
voting broker's own evidence. The intervening lightcurve request no longer
changes that question into bare object existence. Each distinct broker supplies
at most one vote for the same exact candidate identity. Incoming material cannot
supply a missing voting broker's class, and multiple matching rows at one broker
do not supply multiple votes.

One authored general or scoped condition remains attached through ordinary
material requests, initial inside/within/latest clauses and result ordering.
Initial selectors keep their existing semantics; this change does not schedule
new discovery dependencies or move latest after confirmation. In a discovery
query, a general where remains the discovery condition as before and is also the
confirmation proposition. On a named lookup, a bound general where retains the
existing adjacent form's behavior: confirmation evaluates the proposition on its
own evidence instead of first fetching a default broker's implicit classification.

Scoped conditions retain the existing candidate filtering as well as attaching
their exact canonical predicate. For example, this works in either a fresh
lookup or a continuation over its materialized candidates:

```text
with classification from sherlock via lasair where best.class = "SN" and best.score >= 2
with lightcurve via fink
confirm by 1 via lasair
```

The producer, channel, fields and score meaning stay intact. This does not turn
Sherlock reliability into a probability or a Fink-qualified condition into a
Lasair vote. In particular, a scoped broker list's canonical OR is not rewritten
as an unqualified shared proposition or automatically converted into quorum.
Existing confirmation endpoint capabilities must prove the whole question for
every requested voter; otherwise preflight rejects it rather than reporting
existence success. No broader dynamic-field or endpoint coverage is declared.

## Scope boundaries

- An explicit filter, match, or earlier confirm ends proposition attachment.
  A following bare confirm remains an existence question unless the new stage
  supplies another explicit condition.
- Conditions are drawn only from the current script or fragment. A bare confirm
  in a later API call never inherits a previous call's predicate from saved IR.
- Multiple different canonical conditions in one confirmation stage are
  ambiguous. Preflight and direct lowering reject them with an explicit scope
  diagnostic. Write one deliberate Boolean condition for the question; the
  compiler does not guess an AND, OR or nearest-condition preference.
- Repeated identical canonical conditions do not create ambiguity.

Unqualified propositions may be tested independently by several brokers when
their existing mappings supply the fields. Explicit qualifications always narrow
the question. Missing classes remain unknown under negation; a required request
failure remains failure rather than abstention. No taxonomy, winner or consensus
classifier is introduced.

## Implementation

One surface compiler helper determines confirmation predicates and the general
where clauses they consume. Fresh lowering, continuation lowering and capability
preflight share that rule. Existing ConfirmStep, occurrence-local evidence,
runtime, distinct-broker counting, normalization and provenance remain unchanged.

The confirmation capability check now attributes a legacy record's omitted
channel to its own field mapping's broker. This matches normalized predicate
evaluation and admits qualified Fink material without borrowing another source's
channel. No provider recipe, ontology record or new IR field is added.

## Offline checks and handoff

The new replay suite covers nonadjacent layout/material requests; distinct votes
and duplicated rows; unknown classes under NOT; scientific records and provenance
across fresh/continuation forms; exact qualifiers; bare confirmation; immutable
prefixes; stage boundaries; ambiguity before provider calls; required failures;
and unsupported cross-channel propositions. Existing tests cover initial
selectors and downstream confirmation consumers.

Preparation passed all 220 distinct offline cases in the modules below, across
focused and regression runs. No live provider request or remote CI was run.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_confirm_scope.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_live_confirm.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_orchestration_confirmation.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_confirm_downstream.py \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-confirm-proposition-scope-tests.log
```

The live-confirm-named test only compiles/plans and performs no provider I/O.
Run a DSL/registry CI checkpoint after the local checks and squash, since both
surface confirmation scope and shared confirmation admission change. Live
deployment acceptance and final integration CI remain separate requirements.
C4's guarded discovery limits and comparison/native-discovery work remain.
