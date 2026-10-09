# Confirmation evidence recipes (branch 09b)

Branch: `refactor/recipes-09b-confirmation`, based on `main` at `6a8fcee` (PR #268).

The eight existing broker/survey providers now declare target-bound `confirm`
calls using the existing IR operation and target path. For example:

```yaml
recipes:
  confirm:
    - calls:
        - endpoint: objects
          params:
            objectIds: {from: step.target.ids}
```

Each eligible recipe has one required call and binds candidate object identities.
The strict registry compiler verifies that this source uses a physical `target_id`
encoder. Binding retains CSV collections, provider batch sizes, and scalar fan-out.
Targetless workflows obtain IDs from the current candidate view without inserting
runtime values into WorkflowIR. Explicit nonobject target namespaces defer.

Capability validation supplies the exact recipes expanded by the planner. DSL
confirmation checks now call that same orchestration validator. An infeasible
owned declaration cannot fall back to a tagged lookup endpoint. Multiple equally
eligible recipes remain ambiguous, even when they share a physical endpoint.

The established selection policy remains: prefer object lookup evidence, then
history evidence for bare confirmation, and prefer collections within a tier.
For migrated providers, lookup and history tiers derive from existing compiled
lookup/lightcurve recipes rather than operation tags. Unmigrated providers retain
the compatibility path. These tiers do not rank competing declarations within the
same endpoint or invent a provider preference.

Both existence and predicate confirmation require an endpoint-local mapped
`summary.identity.object_id` or `detection.identity.object_id`. Predicate checks
also require every referenced field, producer, and channel on that same endpoint.
Previously the check read family-wide record fields, which combine mappings from
several endpoints. A discovery mapping could therefore falsely establish a field
on an identity lookup response. The resolver now reads individual endpoint field
mappings. A mapped predicate field without mapped object identity cannot establish
a confirmation vote.

Provider mappings still describe possible material. Runtime normalization and
the existing confirmation reducer determine whether each broker's own returned
evidence satisfies the predicate. Distinct-broker quorum, negative votes,
candidate reduction, provenance, downstream binding, and continuation remain
orchestration behavior. No broker combinations or quorum rules are authored in
provider YAML. SQL and the remaining cutover/reuse audit follow separately.

## Local handoff

Tests were not run in the editing environment. Python syntax, YAML parsing,
required physical inputs, whitespace, and bundle structure were checked.

```bash
recipe_branch=refactor/recipes-09b-confirmation
recipe_bundle="$HOME/Downloads/recipes-09b-confirmation.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_confirmation.py \
  tests/test_orchestration_confirm_downstream.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_ir_integration.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_api_continuation.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Resolve confirmation evidence through provider recipes" \
  --body 'Declare target-bound confirmation recipes across the existing broker/survey contracts. Share recipe feasibility between DSL validation and planning, use endpoint-local predicate and identity evidence, and preserve registry-derived lookup/collection preferences. Quorum and vote reduction remain in orchestration. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
