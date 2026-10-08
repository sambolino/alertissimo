# Provider predicate bindings (branch 07)

Branch: `refactor/recipes-07-predicates`, based on merged `main` at
`2a2fde5` (product recipes, PR #265).

ALeRCE LSST's three existing request translations now live beside its recipes:

```yaml
predicate_bindings:
  query_objects:
    - path: classification.provenance.producer.name
      operator: "="
      parameter: classifier
    - path: classification.best.class
      operator: "="
      parameter: class_name
    - path: classification.best.probability
      operator: ">="
      parameter: probability
```

An operator is mandatory and comes from the existing comparison IR. The probability
binding consumes only `>=`, including its equivalent reversed form. `<`, `>`, and
other comparisons retain their existing residual treatment. Parameter names do not
imply operators. This branch does not add SQL expression translation.

The declaration names a physical endpoint once. `CapabilityGraph` compiles each
entry to the existing `RequestConstraintCapability`, validating its parameter,
server-filter membership, and canonical ontology path against that endpoint's
response mappings. Another endpoint's mapping cannot satisfy this check. Duplicate
parameters or path/operator pairs, unknown keys, and omitted operators fail visibly.
The shared capability loader retains strict duplicate YAML key detection.

For current SearchStep recipes, only the first required call owns discovery.
Its compiled `RecipeCall.predicate_bindings` contains its endpoint's translations;
later calls and Get/lookup calls have no search bindings. The planner supplies that
exact tuple to `realize_predicate`. It records predicate realization only on the
discovery plan, so optional or required identity-bound enrichment calls cannot
push the search predicate or independently prune enrichment responses. The existing
candidate dependency continues to carry the discovery survivors.

The single-call semantic-search planner still looks up the selected endpoint's
compiled bindings. Migrating that operation to recipe selection belongs to branch
09; this relocation preserves the existing ALeRCE DSL requests and reuse evidence.

`PredicateRealization` and the binder retain producer/channel qualifiers, partial
AND pushdown, residual OR/NOT, comparison inversion, and conflicting assignment
behavior. A discovery recipe cannot also assign a predicate-bound parameter or
override it through fixed transport values. The compiler rejects that competing
source of request meaning. Execution and normalization models are unchanged.

The former ALeRCE `request_mappings.yaml` was removed after an audit found only the
graph loader, a provider-renaming regression fixture, and CI triggers referring to
it. The fixture now renames `capabilities.yaml`. The compatibility loader and CI
trigger remain for unmigrated providers; declarations in both locations for the
same provider are rejected instead of silently choosing one.

## Local verification and PR

Tests were not executed in the editing environment. Import and check locally:

```bash
recipe_branch=refactor/recipes-07-predicates
recipe_bundle="$HOME/Downloads/recipes-07-predicates.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_residual_pruning.py \
  tests/test_orchestration_execution_coalescing.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Compile provider predicate bindings and scope pushdown to discovery" \
  --body 'Move existing ALeRCE LSST request translations into provider capabilities with explicit IR operators and endpoint-specific mapping validation. Scope recipe predicate realization to discovery calls, preserve residual and qualifier semantics, and reject competing parameter assignments. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
