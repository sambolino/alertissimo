# Required recipe evidence for reuse (branch 09d)

Branch: `refactor/recipes-09d-reuse`, based on `main` at `a9c04e8` (PR #270).

A discovery recipe may enrich candidates with an optional classification call.
Previously, a later required classification retrieval could reuse that call solely
because its endpoint mapped classification records. If the optional attempt
failed, discovery succeeded but the required retrieval failed because its reused
execution did not exist. The planner now leaves that retrieval as a fresh call
bound to candidate IDs. A required enrichment call remains eligible for reuse.

For recipe-owned Search/Lookup operations, both ordinary Get reuse and dynamic
classification material reuse now resolve the selected recipe through capability
validation. The owner plan must match a required call's endpoint, parameter
sources, request constants, and intra-Step dependency. Its compiled mapped outputs
provide record-family and producer evidence. Dependency offsets include preceding
sources, so a later provider's call still matches the correct discovery plan.
An unmatched owned call cannot fall back to the legacy endpoint-family index.

Operations without recipes retain their compatibility evidence. Existing request
projection equality, positive producer requirements, candidate-population checks,
and global-selection restrictions still apply. This branch does not claim mapped
fields are always present in responses or widen retrieval equivalence.

Regression coverage exercises optional versus required enrichment, source offsets,
plan JSON round trips, a failed optional attempt followed by successful required
retrieval, and compiled call outputs that differ from the legacy family index.
The remaining semantic-provider eligibility audit precedes cleanup.

## Local handoff

No tests were run here. Python syntax, whitespace, and bundle structure were
checked. Run the focused suites locally:

```bash
recipe_branch=refactor/recipes-09d-reuse
recipe_bundle="$HOME/Downloads/recipes-09d-reuse.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_lightcurve_forced_reuse.py \
  tests/test_orchestration_supplementary_plans.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_normalization_reuse.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Require selected mandatory recipe evidence for execution reuse" \
  --body 'Prevent optional discovery supplements from satisfying later required retrievals. Ground candidate reuse and dynamic classification material reuse in selected required recipe calls and their compiled outputs, preserving source dependency offsets and unmigrated compatibility. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If GitHub has not registered checks yet, rerun the final command once workflows
appear. After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
