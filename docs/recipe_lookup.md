# Recipe object lookup (branch 06a)

Branch 06d also applies the existing `target_kind` guard to product retrieval
recipes; see `recipe_products.md`. The text below describes the 06a increment.

Branch: `refactor/recipes-06a-lookup`.
Base: `main` at `0daf3de` (PR #261).

The retrieval increment is split by operation to keep each branch reviewable.
This branch activates object lookup; classification and other Get operations
remain subsequent parts of branch 06.

Object lookup now uses provider recipes across all eight broker/survey paths.
The compiled plans retain existing scalar fan-out, integer conversion, collection
encoding, and candidate ownership through Filter/Get steps.

```yaml
lookup:
  - target_kind: object
    calls:
      - endpoint: object
        params:
          objectId: {from: step.target.ids}
  - target_kind: object
    calls:
      - endpoint: objects
        params:
          objectIds: {from: step.target.ids}
```

`target_kind` is required only for lookup recipes. It constrains the existing
`LookupStep.target.kind`, validated by the actual IR model. It identifies the input
namespace, without copying the output's record family. It is rejected on other
recipe operations. There is no condition expression language.

The distinction is necessary because an object-history endpoint can map detection
records while accepting object IDs. Detection outputs cannot establish that an
endpoint accepts alert IDs. Production declarations in this branch support only
objects. Alert IDs remain unsupported for these providers. An authored alert
recipe can be compiled as a valid IR namespace, but activation remains deferred
until a physical alert identity contract is verified.

Activation requires one required call, a direct target-identity source, the existing
physical `target_id` encoder role, and mapped summary object-identity material.
Mappings remain evidence of possible fields, not guaranteed values.

Lasair/ZTF authors both scalar and collection alternatives. Existing cardinality
preference selects the scalar call for one ID and the collection call for multiple
IDs. If only a singular call exists, the binder fans out. Equal alternatives of
the same shape remain ambiguous, including declarations using the same endpoint.

Recipes own migrated lookup providers even for unsupported target kinds or
unsatisfied inputs. There is no fallback to their old operation tags. Providers
without lookup recipes retain legacy resolution during migration. Surface
validation still uses legacy tags until branch 09.

Earlier discovery/lookup execution reuse now checks request constants before
treating mapped fields as reusable material. A narrower authored projection cannot
satisfy a broader Get merely because the physical endpoint is identical.
Equivalent existing default requests can still reuse their execution.

Planner expansion and physical binding use the machinery introduced in preceding
branches. Runtime dependency models, runner, executor, normalization, and physical
endpoint contracts are unchanged.

## Local workflow

Download `recipes-06a-lookup.bundle`, then run in the repository with your virtual
environment active:

```bash
recipe_branch=refactor/recipes-06a-lookup
recipe_bundle="$HOME/Downloads/recipes-06a-lookup.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_dsl_lookup_pipeline.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_lightcurve_forced_reuse.py \
  tests/test_orchestration_execution_coalescing.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Activate object lookup recipes with explicit target namespaces" \
  --body 'Activates object lookup recipes across providers and validates the input namespace against LookupStep. Preserves cardinality preferences, scalar fan-out, and candidate flow. Keeps alert IDs separate and checks request constants before execution reuse. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks briefly have not appeared after pushing, run the watch command again
once GitHub queues them. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

Author-side inspection: Python/YAML syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent.
