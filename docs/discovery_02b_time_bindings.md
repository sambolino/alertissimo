# Bind discovery time windows and preserve their replay context

`within` already reaches WorkflowIR as `TimeContext`, but recipes could not encode
it into physical time bounds. Relative time also needs a stable clock during one
discovery occurrence and its later continuation. This change completes those paths
using the existing recipe compiler, request transforms, binder, and staged execution.

This is PR 02b of the [discovery integration plan](discovery_integration_plan.md),
based on merged PR #294, main `7f7165d`. It activates no production provider recipe
and introduces no architecture layer or replacement workflow/result model.

## Declarations and semantics

The existing `from` and endpoint encoder syntax carries the whole IR context:

```yaml
# Physical endpoint parameter declaration (example fragment).
window_start:
  type: string
  required: true
  bind: time_context
  binding:
    adapter: alertissimo.data_layer.transforms.temporal:time_bound
    adapter_options: {bound: start, encoding: utc_iso}
window_end:
  type: string
  required: true
  bind: time_context
  binding:
    adapter: alertissimo.data_layer.transforms.temporal:time_bound
    adapter_options: {bound: end, encoding: utc_iso}
```

```yaml
# Existing recipe-call params syntax (example fragment).
params:
  window_start: {from: step.time_context}
  window_end: {from: step.time_context}
```

The new registered pure transform supports `bound: start`, `end`, or `range`, with
`encoding: utc_iso`, `mjd`, or `jd`. A range returns an array of the two encoded
bounds. The discovery call must consume the whole context and encode both ends;
a nested `start_time` path or constant replacing one end cannot prove a relative
window. Options and encoder roles are checked at recipe load. The callable remains
in the existing transform allowlist; no arbitrary adapter imports are enabled.

UTC ISO retains microseconds and a `Z` offset. MJD/JD are UTC day numbers within
floating-point precision. The transform performs no TAI/TT conversion, leap-second
representation, timezone guessing, rounding to dates, or boundary shifts. Absolute
datetimes and injected reference instants must have a timezone; explicit offsets
are converted to UTC. Offset, sampling, open-ended, non-positive, and mixed
relative/absolute contexts remain deferred rather than partially implemented.

Actual provider field meaning and inclusive/exclusive boundary rules still need
verification in the subsequent provider PRs. An object's last-detection range is
not interchangeable with an alert-observation window. This generic encoder does
not itself establish that equivalence, pagination, or completeness.

## Clock and execution ownership

- Static admission checks representability without sampling a clock or freezing
  validation-time bounds. Relative intent remains unchanged in WorkflowIR and
  EndpointPlan JSON.
- Binding resolves a relative window using one aware reference instant per Step
  occurrence. Both bounds, all source calls, and target fan-out share that instant.
  The pure transform knows nothing about WorkflowIR or execution clocks.
- `execute_dsl(..., reference_time=aware_datetime)` optionally pins new occurrences
  for reproducibility. Ordinary calls continue to work without this argument.
  The staged and upfront binding entry points accept the same optional argument.
- The existing `StepBindingResult` retains the occurrence reference instant.
  Resolved physical bounds remain in bound parameters and execution provenance;
  they are not substituted back into scientific intent. No separate result model
  or temporal parameter registry is created.
- Continuation reuses the old prefix's recorded clocks and exact physical-call
  comparison. A later injected clock applies to newly appended occurrences only.
  A fresh execution resolves a new window. Changing prior temporal intent or
  replaying different resolved parameters still fails before new provider work.

## Local verification

No tests, builds, apps, or broker requests were run here. Python AST, YAML syntax,
and Git whitespace checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_discovery_time_bindings.py \
  tests/test_recipe_registry.py \
  tests/test_request_transforms.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_required_predicate_bindings.py \
  tests/test_api_continuation.py \
  tests/test_dsl_public_api.py
```

New regressions use temporary provider declarations and minimal synthetic object
summaries. They cover fixed and advancing clocks, UTC offsets, ISO/MJD/JD ranges,
sub-day precision, multiple sources, fan-out, immutable IR/plan round trips, public
validation without a binding clock, missing/invalid windows, and prefix replay.
The DSL CI job includes the new module. The transform is an ordinary Python module
inside the already-packaged transform package, with no new optional dependency.

No new live scenario is required for this binding-only branch. Fink activation,
verified class/time populations, and explicit discovery completeness follow in
PR 03; other providers follow their own audited branches.
