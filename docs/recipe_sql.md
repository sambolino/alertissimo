# SQL binding evidence (branch 09c)

Branch: `refactor/recipes-09c-sql`, based on `main` at `0a8aadb` (PR #269).

`SqlQueryStep` supplies one whole `query` string. Both current Lasair endpoints
instead require physical `selected`, `tables`, and `conditions` parameters. Their
operation tags correctly describe a physical SQL-like API, but do not establish
a translation for the IR query. Previously capability validation and planning
accepted those tags; the binder then rejected the missing canonical query role.
Validation now reports this case as deferred, and planning raises the same
diagnostic before constructing an executable workflow.

The shared discovery resolver also accepts strictly compiled `sql_query` recipes
when a physical endpoint genuinely supports a whole-query binding. Such a recipe
must have one required discovery call, mapped requested record-family evidence,
and a `step.query` source backed by the existing physical `query` encoder role.
For example, a provider with a declared `statement` parameter could use:

```yaml
recipes:
  sql_query:
    - calls:
        - endpoint: query
          params:
            statement: {from: step.query}
```

That example is exercised with a local representative contract, not installed in
the production Lasair registry. The physical parameter name remains provider-local.
The loader rejects a whole-query source assigned to a parameter without a query
role. A constant statement cannot replace the requested IR query, additional
untranslated criteria defer, and competing recipes remain ambiguous. No SQL
parsing, decomposition, predicate-expression generation, or new adapter is added.
Current Lasair `SqlQueryStep` requests remain deferred until a real split-query
translation is implemented and validated.

The existing Lasair cone supplement remains executable: it already authors a
projection and table, and feeds normalized candidate IDs to the validated SQL
membership encoder. It is a `cone_search` recipe, not a whole-query SQL request,
and does not depend on the SQL operation tag for discovery eligibility.

Tests retain the binder rejection for handcrafted invalid plans. The generic
workflow-boundary test now begins with an executable object lookup rather than an
unbound SQL plan. Remaining semantic-provider eligibility and reuse evidence are
the next cutover audit before cleanup.

## Local handoff

No tests were run here. Python syntax, YAML parsing, whitespace, and bundle
structure were checked.

```bash
recipe_branch=refactor/recipes-09c-sql
recipe_bundle="$HOME/Downloads/recipes-09c-sql.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_sql_recipes.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_dsl_ir_integration.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Require whole-query binding evidence for SQL discovery" \
  --body 'Align SQL validation and planning with the existing binder: defer Lasair split-query contracts without a whole-query translation. Resolve declared direct SQL recipes through the shared discovery resolver and validate query encoder roles. Preserve the Lasair cone membership supplement. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
