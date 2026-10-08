# Recipe crossmatch retrieval (branch 06c)

Branch: `refactor/recipes-06c-crossmatch`.
Base: `main` at `4178a67` (PR #263).

This increment activates `get_crossmatch` recipes for the six provider/survey
paths with crossmatch mappings. They retrieve stored associations using the
existing object-ID contracts. Search and position endpoints are excluded from
fresh retrieval even when they map catalog material. ALeRCE has no crossmatch
mappings and remains unsupported.

| Provider | Authored targeted calls | Catalog evidence |
| --- | --- | --- |
| ANTARES/ZTF | `get_by_ztf_object_id` | Fixed catalog qualifiers, including `gaia` |
| ANTARES/LSST | `get_by_lsst_dia_object_id` | Fixed catalog qualifiers, including `gaia` |
| Fink/ZTF | `objects` | Fixed qualifiers from this endpoint, including `panstarrs` |
| Fink/LSST | `sources` | Fixed qualifiers from this endpoint, including `gaia` |
| Lasair/ZTF | `object`, `objects`, `sherlock_object`, `sherlock_objects` | Fixed `tns` on generic object retrievals; dynamic catalogs on Sherlock material |
| Lasair/LSST | `object`, `sherlock_object` | Fixed `tns` on `object`; dynamic catalogs on Sherlock material |

Recipes use existing IR fields and physical encoders:

```yaml
get_crossmatch:
  - calls:
      - endpoint: sources
        params:
          diaObjectId: {from: step.target.ids}
```

Activation requires one required call with mapped crossmatch material, a direct
`step.target.ids` assignment, and the existing `target_id` encoder role. No new
IR vocabulary, selector expression language, endpoint tags, physical API
parameters, or normalization rules are introduced.

A named catalog must match an endpoint-specific fixed producer qualifier,
case-insensitively. Catalogs mapped only by a different endpoint do not count:
for example Fink/ZTF search responses map `gaia_dr3`, but its targeted `objects`
response does not. Lasair's dynamic catalog mappings remain deferred for named
catalog requests. A physical parameter named `catalog` does not establish a
catalog retrieval contract. Unqualified retrieval can still provide dynamic
catalog material; actual rows are interpreted by the existing normalization.

Catalog eligibility is checked before cardinality preference. In particular,
Lasair/LSST `tns` with multiple IDs selects the exact `object` recipe and fans out
instead of letting a collection-only dynamic alternative hide it. Otherwise
existing collection preference remains: plural unqualified Lasair/LSST selects
`sherlock_object`; plural unqualified Lasair/ZTF remains ambiguous between
`objects` and `sherlock_objects`. Equal recipes using the same endpoint are also
ambiguous. Recipe order never breaks ties.

A supplied match radius requires a direct `step.radius` recipe assignment to a
declared server-filter parameter. A physical parameter, default radius, or legacy
operation tag without that assignment is insufficient. None of the production
retrieval recipes has this translation, so their radius requests remain
unsupported. Discovery cone radius is not crossmatch radius evidence. The
registry/binder can carry a separately authored physical radius parameter without
adding special runtime code; a synthetic contract case covers that boundary.

Migrated providers cannot fall back to old tags for unsatisfied or ambiguous
recipes. Unmigrated providers retain the existing target/catalog/radius checks
through a shared legacy compatibility helper. No new provider-specific routing
is added to the planner.

Targetless Gets retain the existing candidate flow. Equivalent lookup material
can reuse its execution when the existing proof accepts the catalog and request
constants. After a Filter changes the candidate view, retrieval binds the current
IDs. Dependency references and recipe inputs survive workflow JSON round trips.
Binding, staged execution, provenance, partitioning, and normalization remain
unchanged. Mappings describe possible material, not guaranteed catalog matches
for every object or proof of every response projection.

## Local workflow

Download `recipes-06c-crossmatch.bundle`, then run in the repository with your
virtual environment active:

```bash
recipe_branch=refactor/recipes-06c-crossmatch
recipe_bundle="$HOME/Downloads/recipes-06c-crossmatch.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_crossmatch_capability.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_normalization.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Activate targeted crossmatch retrieval recipes" \
  --body 'Activates crossmatch recipes across ANTARES, Fink, and Lasair using object-ID bindings and endpoint-specific catalog evidence. Checks catalog eligibility before collection preference, preserves dynamic-catalog deferral and radius restrictions, and retains candidate binding and execution reuse. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared immediately after pushing, rerun the watch command
once GitHub queues them. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

The existing optional live crossmatch acceptance script remains
`PYTHONPATH=. python scripts/live_crossmatch.py`; it reports inconclusive when a
successful live lookup currently has no Gaia counterpart.

Author-side inspection: Python/YAML syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent. Next increment: remaining cutout
and data-product retrievals.
