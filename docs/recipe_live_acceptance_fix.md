# Composite recipe live acceptance fix

Branch: `fix/recipes-live-composite-acceptance`, based on merged `main` at
`504de58` (PR #287).

The live cross-provider scenario still required one Lasair cone plan and three
physical executions. The live continuation scenario still required two first-pass
physical calls. The active cone recipe has a required cone plus an optional,
ID-bound compact summary query, so those assertions reject healthy execution.

Cross-provider acceptance now checks the two-plan discovery shape, required versus
optional roles, and the query's dependency before contacting providers. Successful
execution IDs remain unique across the actual execution results, without a fixed
physical count. Downstream target binding and normalized candidate identity checks
remain in place.

Continuation checks the composite discovery plan and compares recorded first-pass
executor calls with actual staged bindings. This includes optional query attempts
and collection batches. Prior execution IDs, validation without provider calls,
WorkflowIR prefix preservation, vacuous empty survivors, and normalized survivor
identity checks remain. New history calls may use multiple registry batches, but
every call must be Lasair ZTF lightcurves and bind each survivor exactly once.

Offline regressions replay both live scripts using captured fixtures, including a
controlled optional query failure. Cross-provider execution may finish with that
warning. Incremental continuation deliberately refuses a prefix with incomplete
supplementary execution; the failure fixture checks that refusal before any new
provider call and verifies that the original workflow remains active. With a
complete first pass, the continuation fixture retains all candidates and returns
INCONCLUSIVE after replay and binding invariants pass. Separate checks exercise
batched survivors and reject extra calls.
DSL CI watches both changed live scripts; the new regressions join its existing
DSL test glob. Production runtime and provider declarations are unchanged.

No tests or live calls were run here. Python syntax, fixture references, workflow
YAML, unchanged runtime declarations, whitespace, local test paths, handoff shell
syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=fix/recipes-live-composite-acceptance
recipe_bundle="$HOME/Downloads/recipes-live-composite-acceptance.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_live_composite_acceptance.py \
  tests/test_dsl_live_acceptance.py \
  tests/test_api_continuation.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_lasair_ztf_compact_cone_summary.py
```

Then rerun only the failed live checks with the existing LASAIR_ZTF_TOKEN:

```bash
PYTHONPATH=. python scripts/live_acceptance.py \
  --scenario dsl-cross-provider \
  --scenario dsl-incremental-continuation
```

Cross-provider acceptance should pass when providers return valid data. Continuation
passes only when the live filter narrows a non-empty candidate population; keeping
all candidates or selecting none remains INCONCLUSIVE. Fink LSST 504 coverage
remains independently unavailable and is unrelated to this acceptance-script fix.

After local tests and live review:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Align live acceptance with composite Lasair recipes" \
  --body 'Fix stale single-call assumptions in cross-provider and continuation acceptance. Validate required cone plus optional ID-bound summary query, compare first-pass calls with staged bindings, and allow survivor batching while preserving replay and identity invariants. Add offline fixture replays covering successful and failed supplements. Production runtime and provider declarations are unchanged. Validation: focused suites and two live scenarios run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
