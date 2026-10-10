# ALeRCE LSST recipe-owned tag cleanup (branch 10l)

Branch: `refactor/recipes-10l-alerce-lsst-tags`, based on merged `main` at
`df65e7c` (PR #284).

Retire discovery/filter tags from query_objects, object_lookup from query_object,
lightcurve from query_lightcurve, forced_photometry from query_forced_photometry,
classification tags from query_probabilities, and product/cutout tags from
get_stamps. These six endpoints already participate in provider-owned recipes,
including unsupported or deferred request variants.

Keep mixed object-summary, object-history, and lightcurve-component metadata.
Detection/non-detection components, statistics, disabled features/vocabularies,
and catalog enrichment retain their declarations. LSST get_avro is disabled and
has no authored recipe; its data-product/raw-alert tags remain. Crossmatch has no
provider recipe; shared unowned mapped-material eligibility remains available.

Extend the architecture retirement check to both ALeRCE surveys, with AVRO
retirement restricted to ZTF. This module already runs in registry CI. The
incompatible owned-discovery fixture supplies its own object_search fallback tag,
so it still verifies that an infeasible owned recipe rejects legacy fallback.
Forced retrieval validation now inspects the compiled get_forced_photometry
recipe and its endpoint instead of relying on the retired tag.

Existing regression targets cover LSST classifier selector deferral and shared
discovery-material reuse, optional forced-photometry evidence, target binding,
confirmation tiers, and product normalization deferrals. The classifier argument
remains absent from LSST query_probabilities; discovery proof remains necessary
for qualified material reuse.

No recipes, predicate bindings, scientific mappings, feature IDs, physical
parameter/transport/output contracts, or runtime code change. No tests were run
here. Python syntax, provider YAML, the exact declaration diff, whitespace,
local test paths, handoff shell syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10l-alerce-lsst-tags
recipe_bundle="$HOME/Downloads/recipes-10l-alerce-lsst-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_alerce_registry_architecture.py \
  tests/test_alerce_lsst_authoritative_payloads.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_classification_material.py \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_orchestration_product_recipes.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_classification_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned ALeRCE LSST operation tags" \
  --body 'Remove redundant discovery, lookup, photometry, classification, and stamp-product tags from six ALeRCE LSST endpoints. Preserve mixed metadata, disabled AVRO declarations, classifier deferral and discovery-material reuse, optional forced evidence, and product deferrals. Extend architecture retirement coverage to both surveys and make remaining test evidence explicit. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
