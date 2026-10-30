# R1 — Preserve DSL predicates and reject unsafe early evaluation

Branch: `fix/dsl-predicate-preservation`.
Base integration: `6aa9b161c65fb1efb906d74f9a5ae7403a89e87e`.
Target: `integration/discovery-completion`; keep main-target PR #329 draft.

This is the first corrective PR from the
[semantic audit](discovery_semantic_audit.md) and
[classification evidence plan](classification_evidence_design_plan.md).
The bundle also carries the previously prepared ANTARES status-reporting fix
`f496197` and audit/design documentation `823f255`, which were not on remote
integration when this branch was prepared. Neither prerequisite changes the
scientific predicate evaluator.

## Changes

- A fresh explicit lookup retains general `where` and scoped `with ... where`
  conditions. Initial lookup conditions become an existing FilterStep after
  requested initial retrievals and before later Filter/Confirm/Match operations.
  General qualified conditions can supply their implied existing Get operation;
  an equivalent explicit requirement does not issue a duplicate retrieval.
  The surface model accepts lookup `where`, including after an initial `with`;
  a subsequent explicit `filter` still ends the initial candidate pass. The
  existing discovery-only restriction on general `where` after `with` remains
  until C4 supplies the corresponding material-aware scheduling.
- A top-level where/inside/within/latest after an explicit filter is rejected
  before execution. Those clauses used to fall through without realization.
  Existing scoped refinement after a filter and in continuation remains valid.
- Inside/within/latest on an explicit lookup remains rejected by the existing
  surface guard until a supported selection realization exists. Existing parser
  guards likewise reject late candidate constraints; the lowering guards also
  protect directly supplied surface models. Public regressions assert the
  earliest rejection stage rather than expecting parsing to succeed.
- A selected discovery recipe must materialize every reference in the residual
  evaluated on its first call. The check uses that call's compiled outputs,
  including SQL projection restrictions, qualified producers/channels and dynamic
  field segments. It cannot borrow material from a later supplement/Get.
- Unproven discovery dependencies now raise PlanningDeferredError before any
  provider call. For example, an ALeRCE cone cannot evaluate a Fink condition on
  its own response and falsely return an empty candidate population.

The last change is a correctness guard. The planned C4 work will realize such
requests through material-aware planning without asking users to reformulate
their scientific condition. R1 does not introduce that larger scheduling feature.
It does not change native discovery filters, canonical predicates, provider
fields, measurement retention, Confirm quorum evaluation or version selection.

R2 still owns assertion correlation and missing-evidence/negation repair. The
broader classification retrieval/model-selection and Confirm-scope work stays
in the subsequent plan; R1 is not a claim that every initial and continuation
classification formulation is already interchangeable.

## CI while #329 stays open

The three workflows retain their integration-base exclusions for the small PRs.
Their validate jobs additionally skip automatic execution when the head is
`integration/discovery-completion` and the main-target PR is draft. Otherwise
each small integration squash would trigger #329's complete CI again.

Manual workflow_dispatch still executes the jobs. Other PRs retain their normal
behavior. The ready_for_review event is enabled: marking #329 ready runs all
three jobs, as do subsequent updates while it is ready. A skipped job on a draft
is not validation of the new head and must never be used as the final merge gate.
Retain final closeout cleanup and successful checks on the actual final SHA.

No CI was started for R1 during preparation. After R2 changes the shared evaluator,
one manual DSL/registry checkpoint is recommended on the merged integration SHA:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
```

Keep #329 draft at that checkpoint. Full final main-target CI follows when all
release blockers are resolved and the PR is marked ready.

## Local verification

No project imports, tests, builds, applications or broker requests ran during
preparation. Static Python AST, workflow YAML, whitespace and bundle checks were
performed. The new regression module uses two synthetic objects through the
public API, real registry/planner/normalization and a recording fixture executor.
It checks rejection of the nonmatching candidate, preservation of all survivor
measurements, immutable continuation, correct target calls, explicit unsupported
clauses, and deferral before provider execution. It also keeps admitted mapped
residuals and dynamic photometric fields covered.

Run locally from the feature branch:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_predicate_preservation.py \
  tests/test_dsl_surface.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_alerce_classification.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_api_continuation.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_alerce_semantic_search.py \
  tests/test_fink_semantic_search.py \
  tests/test_lasair_semantic_search.py \
  tests/test_antares_semantic_search.py \
  tests/test_dsl_live_discovery.py \
  2>&1 | tee /tmp/alertissimo-dsl-predicate-preservation-tests.log
```

The last module tests the previously prepared reporting fix offline; its name
does not mean it contacts a provider. No additional live requests are required
for this compiler/planner repair.
