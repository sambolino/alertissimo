# Recipe cone follow-ups (branch 04)

Branch: `refactor/recipes-04-lasair-cone`.
Base: `main` at `7aa3236` (PR #259, including its CI assertion fix).

Lasair/ZTF now authors its compact summary follow-up in the provider's
`capabilities.yaml`. The planner expands the compiled recipe into ordinary
`EndpointPlan` values. It no longer checks for Lasair or inserts a query on its own.

```yaml
broker: lasair
origin: ztf
recipes:
  cone_search:
    - calls:
        - endpoint: cone
          params:
            ra: {from: step.ra}
            dec: {from: step.dec}
            radius: {from: step.radius}
        - endpoint: query
          required: false
          params:
            conditions:
              from: {call: 0, path: summary.identity.object_id}
            selected:
              value: objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax
            tables: {value: objects}
            limit: {value: 100}
            offset: {value: 0}
```

`cone_search` remains the existing IR discriminator. The requested record family
comes from the Step and is checked against required discovery-call mappings.
Recipe authors do not repeat it. Optional output mappings cannot establish that
the recipe satisfies a requested discovery family.

The call reference becomes the existing `PlanCandidateInputRef`, adjusted for any
earlier plans from other requested sources. The physical parameter's compiled
source is the existing runtime role `target_id`; it does not read a nonexistent
`target` field from `ConeSearchStep`. Tuple sources still read actual Step fields.
All source metadata survives `WorkflowRun` JSON serialization.

The existing staged runner supplies normalized identities. The binder uses the
endpoint's existing SQL membership encoder, identifier validation, and maximum of
100 identities per request. The recipe supplies values and constants, without
authoring SQL or duplicating encoder configuration.

Existing behavior remains: one IR Step; a required cone plan; an optional query;
rich summaries consolidated from successful calls; a warning and thin results if
the query fails; no query invocation after an empty cone result. Runner, executor,
normalizer, mappings, and physical endpoint contracts are unchanged.

The DSL CI job now includes the existing compact-summary fixture suite, alongside
the orchestration tests that exercise compiled recipes and saved runtime plans.

Activation in this increment supports a required discovery call followed by
retrieval calls bound to that discovery's identities. Independent follow-up calls
and dependencies on follow-up outputs remain deferred without legacy fallback.
Undeclared temporal, magnitude, and legacy criteria inputs still defer. Predicate
translation and selection remain later increments; this branch does not establish
new response projection or predicate guarantees.

For providers without a recipe, legacy atomic cone selection remains available.
Removing Lasair's follow-up declaration leaves an atomic cone: there is no hidden
provider-specific supplement. The existing lightcurve supplement is handled in
branch 05.

## Local workflow

Download `recipes-04-lasair-cone.bundle`, then run these commands in the repository
with your virtual environment active:

```bash
recipe_branch=refactor/recipes-04-lasair-cone
recipe_bundle="$HOME/Downloads/recipes-04-lasair-cone.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_runtime.py \
  tests/test_orchestration_runner.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Declare Lasair cone summary follow-up in provider recipes" \
  --body 'Moves the Lasair ZTF cone summary query into the provider recipe and expands calls through existing candidate dependencies. Removes the provider-specific planner supplement while retaining batching, optional failures, and empty-result behavior. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If GitHub briefly reports no checks after pushing, run the watch command again
once the jobs appear. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

Author-side inspection: Python syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent.
