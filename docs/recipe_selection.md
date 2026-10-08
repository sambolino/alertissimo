# Latest selection (branch 08)

Branch: `refactor/recipes-08-selection`, based on `main` at `a0011fb` (PR #266).

Previously `latest` was parsed into SearchSelection but ignored during planning
and execution. This branch gives it an explicit runtime meaning: select the N
objects with greatest `summary.time.last_mjd` after residual filtering and object
consolidation. Equal timestamps sort by `(origin, object_id)` ascending. Multiple
summary records retain their fields and provenance; an object's recency is the
greatest valid last-detection MJD among its records. Missing identity, missing
recency, nonnumeric values, and nonfinite values raise a selection error.

The first supported provider contract is ALeRCE ZTF `query_objects`, for semantic
and atomic cone searches:

```yaml
selection_bindings:
  query_objects:
    latest:
      path: summary.time.last_mjd
      params:
        order_by: {value: lastmjd}
        order_mode: {value: DESC}
```

The [official ZTF client source documentation](https://alerce.readthedocs.io/en/stable/_modules/alerce/ztf_search.html)
lists `lastmjd` as an ordering field, ASC/DESC as directions, and page/page_size as
pagination controls. The [object response documentation](https://alerce.readthedocs.io/en/stable/models/object.html)
defines `lastmjd` as the last detection's MJD. Existing provider mappings connect
that raw field to the canonical recency field. These references were checked for
this branch; no live API acceptance or test execution was performed here.

The compiler validates the IR selector, endpoint-local recency and object-identity
mappings, ordering parameters/constants, mapped JSON response mode, and the
executor's existing exhaustive page/page_size contract. It rejects competing
predicate/recipe assignments and fixed single-page or count-only contracts.
No limit translation is authored: `page_size` remains a transport batch size.
The executor exhausts all pages using its existing safety policy; reaching that
policy limit raises an error instead of returning a truncated latest-N claim.

Only complete atomic summary discoveries activate this contract. Selection also
requires mapped predicate material, including qualifiers, and no untranslated
criteria/time context. Other providers, ALeRCE LSST, and composite discoveries
defer until their response/population contracts are established. In particular,
ALeRCE LSST discovery does not currently map the recency key. A later optional
enrichment mapping cannot establish the discovery population's selection key.

The semantic reducer runs once across the consolidated Step candidate universe;
it does not truncate each source, page, or dependency batch. Physical normalized
execution groups remain available for audit. A selected immutable material
snapshot owns the semantic Step result and the downstream target IDs. Selection
runs in both final normalization and staged candidate flow, including replayed
prefixes during continuation. Full discovery executions cannot be reused as an
enrichment view after selection; selected IDs bind a fresh retrieval instead.

DSL capability validation reuses the existing candidate lowering and orchestration
resolver for `latest`. It now reports the same deferrals before execution. Result
view `order by` remains separate from WorkflowIR candidate selection. The offline
confirmation fixture now includes the recency field it needs; UI compiler tests
expect unsupported multi-survey latest requests to defer.

## Local handoff

```bash
recipe_branch=refactor/recipes-08-selection
recipe_bundle="$HOME/Downloads/recipes-08-selection.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_selection_recipes.py \
  tests/test_dsl_ir_integration.py \
  tests/test_dsl_public_api.py \
  tests/test_dsl_confirm.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_endpoint_pagination.py \
  tests/test_orchestration_normalization.py \
  tests/test_orchestration_residual_pruning.py \
  tests/test_orchestration_confirm_downstream.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_api_continuation.py
```

If your environment has the UI test dependencies, also check
`PYTHONPATH=. python -m pytest -q tests/test_app_search_portfolios.py`.

After tests pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Apply canonical latest selection after complete discovery" \
  --body 'Activate the verified ALeRCE ZTF recency ordering contract and apply latest globally after exhaustive pagination, residual pruning, and object consolidation. Preserve physical audit groups and feed selected IDs to downstream retrievals and continuation; defer unproven selection contracts. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and passing CI:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
