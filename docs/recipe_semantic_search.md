# Semantic discovery recipes (branch 09a)

Branch: `refactor/recipes-09a-search`, based on `main` at `e325eaa` (PR #267).

ALeRCE ZTF and LSST now declare their existing semantic discovery endpoint:

```yaml
recipes:
  semantic_search:
    - calls:
        - endpoint: query_objects
```

The operation is the existing `SemanticSearchStep.op`. No parallel record-family
selector is authored: endpoint-local mappings establish possible output material.
The declaration assigns no ordinary parameters, so physical endpoint defaults
remain authoritative. Predicate translations and verified selection metadata are
compiled onto this discovery call using the contracts from branches 07 and 08.
ALeRCE ZTF latest selection remains supported; LSST latest remains deferred.

Cone and semantic discovery use one recipe feasibility implementation consumed by
both public capability validation and planning. The first call must be required
and map the requested record family. Later calls must consume its normalized
object identities. Missing family evidence stays unsupported, competing recipes
stay ambiguous, and infeasible owned recipes cannot fall back to legacy endpoint
tags. Unmigrated operation/provider pairs retain the compatibility path.

Nonempty `criteria` and unbound `time_context` now defer for migrated semantic
discovery. Previously broad operation validation accepted those fields although
the binder supplied no corresponding request values. This branch introduces no
translation for them. Predicate operators and residual evaluation retain their
existing semantics; in particular a probability parameter consumes only the
authored `>=` comparison.

This is the first small cutover branch. Other semantic-search providers, SQL,
confirmation evidence, and reuse proof remain for subsequent branches. The SQL
audit found that Lasair exposes separate `selected`, `tables`, and `conditions`
parameters, while `SqlQueryStep` supplies one `query` string. The existing binder
already rejects the missing query binding. An operation tag alone does not prove
a working SQL translation, and this branch invents no SQL parser or encoder.

## Local handoff

No tests were executed in the editing environment. Python syntax, changed YAML,
whitespace, and Git bundle structure were checked.

```bash
recipe_branch=refactor/recipes-09a-search
recipe_bundle="$HOME/Downloads/recipes-09a-search.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_dsl_ir_integration.py \
  tests/test_dsl_live_material_lineage_matrix.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Resolve ALeRCE semantic discovery through provider recipes" \
  --body 'Activate ALeRCE ZTF/LSST semantic-search recipes through the shared cone/discovery resolver. Preserve explicit predicate and latest contracts, ambiguity, and legacy compatibility for unmigrated providers. Defer criteria/time inputs without a declared translation. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
