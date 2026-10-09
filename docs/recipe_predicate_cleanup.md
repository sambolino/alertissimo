# Retire legacy request translations (branch 10a)

Branch: `refactor/recipes-10a-predicate-cleanup`, based on merged `main` at
`b6ab465` (PR #273).

All production request translations already live in provider `capabilities.yaml`.
The remaining `request_mappings.yaml` loader was used only by a compatibility
regression fixture. Graph construction now rejects that retired file and directs
provider authors to `predicate_bindings` in `capabilities.yaml`. It cannot supply
translations when capabilities are absent, nor compete with the current format.

The duplicate parser and recipe fallback have been removed. The existing compiled
`RequestConstraintCapability`, endpoint inspection API, recipe call ownership,
explicit operators, qualifier handling, and residual evaluation remain in use.
DSL CI now watches all provider YAML contracts, so physical contract changes and
accidentally restored legacy files receive the same validation coverage.

The consumer audit found physical `bind`/`binding.roles` still used by encoders,
recipe validation, normalized identity, and provenance inspection. Operation tags
still serve DSL requirement evidence and unowned compatibility paths. This branch
retains those declarations; later cleanup must resolve their consumers first.
The central legacy runtime capability registry is a separate consumer boundary.

No tests were run in the editing environment. Syntax, YAML, whitespace, and bundle
structure were checked. Regression coverage replaces legacy-format support with
rejection for competing, legacy-only, and absent capability declarations.

## Local handoff

```bash
recipe_branch=refactor/recipes-10a-predicate-cleanup
recipe_bundle="$HOME/Downloads/recipes-10a-predicate-cleanup.bundle"

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
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_search_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire legacy request mapping declarations" \
  --body 'Remove the obsolete request_mappings.yaml parser and recipe fallback after auditing production translations. Reject retired declarations with a predicate_bindings migration diagnostic and watch all provider YAML contracts in DSL CI. Preserve compiled predicate evidence and physical encoder metadata. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks are reported yet, rerun the final command once workflows appear.
After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
