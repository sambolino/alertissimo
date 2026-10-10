# Fink ZTF recipe-owned tag cleanup (branch 10i)

Branch: `refactor/recipes-10i-fink-ztf-tags`, based on merged `main` at
`02c4564` (PR #281).

Retire object_lookup and lightcurve from objects, spatial_search from conesearch,
and the full operation_types block from cutouts. Provider recipes own lookup,
lightcurve, cone search, classification, crossmatch, confirmation, cutout, and
data-product intent. Product recipes remain deferred where their physical
response modes lack compatible normalization evidence; tag removal does not
make those products executable.

Objects retains object_history metadata; conesearch retains alert_search.
Latest/class-tag, anomaly, solar-system, statistics, and resolver contracts are
unchanged. Their compatibility tags still describe unowned operations or
specialized populations. Generic semantic discovery remains deferred. Fink LSST
is outside this branch.

The Python consumer audit found shared unowned-operation routing, default
confirmation tiers, a legacy cone fixture, and product encoder inspection.
Owned operations already consume recipes and confirmation supplies recipe-derived
tiers. The legacy cone regression now supplies its own geometric tag after
removing recipes and verifies rejection without it. Product encoder checks locate
the physical endpoint through its compiled get_cutout call for either survey.

Architecture coverage checks retirement of the migrated tags. Include the Fink
architecture module in registry CI's paths and test command. Existing recipe,
binding, product-deferral, DSL, and frozen ZTF payload suites exercise the actual
provider declarations. Physical roles, encoders, response controls, mappings,
feature IDs, runtime code, and executor behavior are unchanged.

No tests were run here. Python syntax, provider/workflow YAML, the exact
declaration diff, whitespace, local test paths, handoff shell syntax, and bundle
structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10i-fink-ztf-tags
recipe_bundle="$HOME/Downloads/recipes-10i-fink-ztf-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_fink_registry_architecture.py \
  tests/test_fink_ztf_authoritative_payloads.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_product_recipes.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_crossmatch_recipes.py \
  tests/test_dsl_classification_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned Fink ZTF operation tags" \
  --body 'Remove redundant lookup, lightcurve, spatial-search, and product tags from three Fink ZTF endpoints. Preserve mixed compatibility metadata and product/discovery deferrals. Make the legacy cone fixture explicit, inspect product encoders through compiled recipes, and include Fink architecture checks in registry CI. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
