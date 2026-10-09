# ANTARES recipe-owned tag cleanup (branch 10h)

Branch: `refactor/recipes-10h-antares-tags`, based on merged `main` at
`681639e` (PR #280).

Remove object_lookup and lightcurve_lookup from get_by_ztf_object_id and
get_by_lsst_dia_object_id. Remove spatial_search from both cone_search contracts.
Provider recipes already own those operations, as well as targeted crossmatch
and confirmation. Lookup namespace checks, lightcurve history proof, native cone
encoding, and confirmation tiers continue through shared recipe validation.

These endpoint declarations mix migrated tags with other metadata. Keep
locus_lookup, locus_search, and object_summary in this branch. Leave get_by_id,
LSST solar-system lookup, and generic Elasticsearch search declarations intact.
Generic semantic discovery still requires an untranslated physical query and
remains deferred. A specialized locus-search tag does not establish generic
discovery support.

The Python consumer audit found legacy routing in shared unowned-operation
resolution and default confirmation tiers. Migrated ANTARES operations supply
recipe evidence, and confirmation supplies recipe-derived tiers explicitly.
No legacy test removes ANTARES recipes while relying on the retired tags.
Python-client paths, native SkyCoord/Angle adapters, physical target roles,
cardinality, null/iterator outputs, mappings, and feature IDs are unchanged.

The architecture suite now admits the existing capabilities.yaml declaration.
Its lightcurve check uses the authored endpoint and step.target.ids assignment,
the physical target encoder, and mapped alert history. It checks removal of the
migrated tags. Add this module to registry CI's paths and test command so these
provider checks run alongside the frozen payload regressions.

No tests were run here. Python syntax, provider/workflow YAML, the exact
declaration diff, whitespace, local test paths, handoff shell syntax, and bundle
structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10h-antares-tags
recipe_bundle="$HOME/Downloads/recipes-10h-antares-tags.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_antares_registry_architecture.py \
  tests/test_antares_lsst_authoritative_payloads.py \
  tests/test_antares_ztf_authoritative_payloads.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_antares_cone_binding.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_confirmation_recipes.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_crossmatch_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Retire recipe-owned ANTARES operation tags" \
  --body 'Remove redundant object-lookup, lightcurve, and spatial-search tags from ANTARES ZTF and LSST endpoints. Preserve mixed compatibility metadata, generic discovery deferral, native cone encoders, and response mappings. Establish architecture lightcurve checks through recipes and include the provider architecture suite in registry CI. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
