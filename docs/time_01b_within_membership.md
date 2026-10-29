# Verify candidate temporal membership before selection

This is **Time 01b**, based on merged Time 01a PR #305, main `55b6c2f`.
It completes the shared evidence-checking prerequisite for default, first, and
last within. Production provider activation follows, beginning with ALeRCE ZTF.
No existing provider YAML is activated or changed in this branch.

## Resulting behavior

A recipe can now identify the required call and payload branch that establish
its temporal selection. Normalized candidate membership is checked before
latest selection and before surviving IDs supply downstream calls. The same
check runs in offline workflow normalization using the original occurrence clock.

Default within needs a detection timestamp inside the closed interval. History
summary overlap is insufficient: an object observed on both sides of a past
interval can still have no detection inside it. First/last use the corresponding
mapped authoritative summary field. They do not infer an extremum from a partial
loaded lightcurve. All records and measurements of a surviving candidate remain
in its Portfolio; physical execution groupings remain available for audit.

An observed positive detection proves membership even without a complete history.
When no witness is found, rejection requires declared complete relevant history
and a successful required evidence call. Unknown coverage, missing/invalid time
material, ambiguous summary dates, or a missing pinned clock raise the explicit
`TimeSelectionError`; they never become a successful empty population.
Complete empty discovery and complete empty histories remain valid empty results.

## Declaration within the existing recipe

The optional recipe-local `time_selection` declaration is compiled beside calls,
predicate bindings, and latest evidence. For example, this **fixture** describes
call 1 of an ALeRCE-shaped recipe, not a new production API guarantee:

```yaml
time_selection:
  mode: detection
  method: material
  call: 1
  payload: query_lightcurve.detections
  complete: true
  time_scale: utc
```

- Mode is detection/first/last and must match the requested TimeContext. A temporal
  alternative is not eligible for a request without the corresponding window.
- Material selection verifies a safely discovered candidate superset. Native
  selection requires encoded bounds and complete evidence on the discovery call.
- Evidence must come from a required call in the same recipe. A later call must
  consume the discovery identities. Its named payload must map the relevant
  detection or summary time; a detection payload must also map ordinary
  photometry, preventing a non-detection-only branch from being claimed as proof.
- The payload branch, execution IDs, required plan dependency, origin, and broker
  scope the runtime records. Other channels, other executions, forced-photometry
  branches, and upper-limit branches cannot supply the witness.
- Only explicitly declared UTC MJD material is admitted here. This does not infer
  Rubin UTC/TAI equivalence or create a new time-scale conversion layer.
- Explicit projections must contain the evidence fields. Mapping possibility
  alone cannot make a column appear in the selected response.

Completeness is a provider-contract assertion to verify during activation, not a
fact inferred from row counts. The current executor's pagination/cap errors and
required-call failures still prevent silently accepting truncated executions.
Declaring complete on an upstream response that is actually capped would be an
incorrect provider declaration; this branch makes no such production claim.

The existing time-bound adapter accepts an explicit mode option. Its default
remains detection; first/last cannot be encoded through an ordinary detection
window accidentally. Matching first/last recipe evidence is required at loading.

The existing RecipeCapability/EndpointPlan gain their small typed evidence
metadata, and StepRun persists the pinned `time_reference` from the existing
binding clock. TimeContext stays relative in IR. There is no new semantic Step,
result/Portfolio model, planner service, dependency, framework, or architecture
layer. Existing native Fink discovery keeps its established behavior while
individual providers migrate to explicit evidence declarations.

## Execution reuse and latest

A later enrichment reusing raw history now restricts its semantic material to the
preceding surviving candidate IDs. It keeps raw execution audit intact. This
prevents a rejected history-gap candidate reappearing through a reused execution
and avoids fetching a compatible history again.

Already-proven single-call latest contracts can compose with declared temporal
evidence: temporal checks precede global object ranking. This branch does not
relax the existing guards for unproven composite latest or activate Lasair/Fink
latest. The later shared/provider latest milestones remain in the plan.

Relative intervals use the same execution-time reference already held by binding
and incremental replay. Offline normalization never samples a new now. Changing
mode or proof changes the semantic/physical prefix and invalidates incompatible
continuation; unchanged prefixes replay their calls and select the same IDs.
For material-based windows with no dates in the physical request, continuation
also checks that the binding clock agrees with the persisted occurrence clock.

## Verification on Veljko's machine

No tests, builds, project imports, apps, or live calls ran here. Python AST, YAML
syntax, Git whitespace, and bundle checks were performed. New coverage uses small
synthetic ALeRCE-shaped contracts and responses; it is not a live provider audit.
The new module is included by the existing DSL CI orchestration glob.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_time_membership.py \
  tests/test_dsl_within_modes.py \
  tests/test_discovery_time_bindings.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_normalization.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_api_continuation.py
```

Cases cover historical gaps and newer detections; inclusive bounds; payload,
execution, and broker ownership; positive and unproven negative evidence; empty
histories/discovery; all measurements retained; first/last checks before latest;
identity-scoped reuse; offline clock replay; continuation proof changes; and
invalid/optional/unprojected evidence declarations. Existing syntax and native
binding suites protect the preceding behavior.

Next after merge: **Time 02 — activate ALeRCE ZTF default/first/last within** with
verified upstream prefilters, history coverage, and request range composition.
Classification joins and remaining Rubin discovery remain at the end for the
user-requested discussion.
