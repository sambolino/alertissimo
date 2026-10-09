# Semantic-discovery eligibility (branch 09e)

Branch: `refactor/recipes-09e-discovery`, based on `main` at `b78b94e` (PR #271).

The remaining legacy discovery audit found two distinct missing proofs. ANTARES
search endpoints require a physical query dictionary that `SemanticSearchStep`
does not supply. Fink search aliases describe cone, anomaly, class-tag, and other
specialized populations; their tags alone cannot choose a population or translate
the IR intent. In particular, removing candidates with missing inputs must not
silently choose Fink ZTF's parameter-free anomaly endpoint for generic discovery.

IR capability validation and planning now defer these Fink and ANTARES requests.
Legacy semantic discovery requires an `object_search` declaration with no missing
mandatory caller parameters. Untranslated criteria and time context also defer.
Providers can declare an explicit recipe to supply physical inputs or establish
their discovery population. ALeRCE's existing recipes remain authoritative;
Lasair's cone/SQL-only surface remains unsupported for generic semantic discovery.
Cone requests and targeted retrievals retain their existing contracts.

`EndpointCapability.required_params` exposes physical inputs still required from
the caller after parameter defaults and provider/endpoint fixed values. It is
compiled from existing endpoint declarations, with no new authored YAML fields.
False and zero defaults count as supplied. The executor now accepts fixed values
as satisfying required inputs, matching the binder and recipe compiler; fixed
values still take precedence and unknown caller parameters still fail.

Mixed recipe/legacy discovery now uses the same eligibility check for wildcard
sources. An explicit unsupported/deferred source is still checked independently;
it is not dropped because another requested source is feasible.

Regressions cover real providers, wildcard and explicit source constraints,
specialized endpoints without mandatory parameters, required query inputs, an
authored recipe supplying a physical query, and effective fixed/default values
through a captured transport. The query example uses a local representative
contract; it does not install a query translation for ANTARES or Fink.

This branch changes the orchestration resolver. DSL candidate checks still have
their legacy summary-presence path; aligning those checks with the lowered IR
resolver is the next small cutover branch before compatibility cleanup.

## Local handoff

No tests were run here. Python syntax, YAML parsing, whitespace, and bundle
structure were checked.

```bash
recipe_branch=refactor/recipes-09e-discovery
recipe_bundle="$HOME/Downloads/recipes-09e-discovery.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_capability_graph.py \
  tests/test_endpoint_execution.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_sql_recipes.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_dsl_live_material_lineage_matrix.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Require executable semantic-discovery contracts" \
  --body 'Defer generic semantic discovery for specialized legacy populations and missing required physical inputs, including wildcard recipe resolution. Compile required caller parameters from existing defaults and fixed values, and align fixed-parameter execution with binding and recipe validation. Preserve declared ALeRCE discovery, cone requests, and targeted retrievals. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks are reported yet, rerun the final command once workflows appear.
After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
