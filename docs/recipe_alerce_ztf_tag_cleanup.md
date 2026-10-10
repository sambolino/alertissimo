# ALeRCE ZTF recipe-owned tag cleanup (branch 10k)

Branch: `refactor/recipes-10k-alerce-ztf-tags`, based on merged `main` at
`50af266` (PR #283).

Retire discovery/filter tags from query_objects, object_lookup from query_object,
lightcurve from query_lightcurve, forced_photometry from query_forced_photometry,
classification tags from query_probabilities, product/cutout tags from get_stamps,
and data_product_lookup from get_avro. Provider recipes already own these
operations, including unsupported or deferred request variants.

Keep mixed object-summary, object-history, lightcurve-component, and raw-alert
metadata. Detection/non-detection components, magnitude statistics, features,
vocabularies, and catalog enrichment retain their declarations. Crossmatch has
no provider recipe; existing mapped-material eligibility remains in the shared
unowned resolver. ALeRCE LSST cleanup is separate.

The Python consumer audit includes shared unowned-operation routing, default
confirmation tiers, and fixtures that remove recipes. The legacy discovery and
confirmation regressions now supply their own tags and exercise both surveys,
so production migration cannot invalidate the compatibility fixture. Owned
confirmation continues to supply recipe-derived lookup/history tiers.

Architecture checks accept optional operation tags and enforce the migrated
declarations' retirement. Add this module to registry CI's paths and test command.
Existing selection tests cover ZTF latest ordering and complete pagination;
photometry tests cover optional forced evidence and execution reuse;
classification tests cover the qualified selector and target binding; product
tests preserve normalization deferrals. Scientific mappings and physical
parameter/transport/output contracts are unchanged.

No recipes, predicate/selection bindings, feature IDs, encoders, runtime code,
or executor behavior change. No tests were run here. Python syntax, provider and
workflow YAML, the exact declaration diff, whitespace, local test paths, handoff
shell syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10k-alerce-ztf-tags
recipe_bundle="$HOME/Downloads/recipes-10k-alerce-ztf-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_alerce_registry_architecture.py \
  tests/test_alerce_ztf_endpoint_contracts.py \
  tests/test_alerce_ztf_authoritative_payloads.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_lightcurve_forced_reuse.py \
  tests/test_orchestration_classification_recipes.py \
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
  --title "Retire recipe-owned ALeRCE ZTF operation tags" \
  --body 'Remove redundant discovery, lookup, photometry, classification, and product tags from seven ALeRCE ZTF endpoints. Preserve mixed metadata, latest selection, classifier binding, optional forced evidence, and product deferrals. Make legacy discovery/confirmation fixtures explicit across both surveys and add ALeRCE architecture coverage to registry CI. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
