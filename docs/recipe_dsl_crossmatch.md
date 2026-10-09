# Shared DSL catalog retrieval validation (branch 10c)

Branch: `refactor/recipes-10c-dsl-crossmatch`, based on merged `main` at
`e1f36ff` (PR #275).

DSL crossmatch requirements previously accepted any provider-wide mapping with
an exact catalog qualifier. For example, Fink ZTF maps Gaia DR3 on search
responses, while its targeted object retrieval does not provide that catalog.
The DSL could report support before the canonical GetCrossmatch resolver rejected
the request. An owned recipe with a constant unrelated target could also remain
supported through its mapped catalog records.

Explicit `with crossmatch from <catalog>` requirements and implied crossmatch
references now use the same pure `_lower_requirement` route introduced in 10b.
The resulting GetCrossmatch operation feeds `validate_step_capabilities`, which
owns catalog compatibility and target-binding evidence. Status and per-source
reason are shared with IR validation; no provider call or endpoint selection is
performed during the DSL check.

Supported checks retain qualified semantic-record labels, with endpoint names
restricted to eligible retrievals. Provider-wide aggregation cannot add another
endpoint to this evidence. Deferred and unsupported checks keep the resolver's
diagnostic and have no eligible endpoint evidence. Dynamic catalog mappings
remain deferred; they do not become wildcard catalog selectors. The existing
report schema, clause location, producer qualifier, source overrides, and
candidate origins remain intact. Local methods and ontology gates are unchanged.

The regression cases cover production catalog statuses, broker overrides across
origins, recipes without operation tags, scoped evidence despite additional
search mappings, an unusable owned recipe, and implied catalog requirements.
Classification requirements remain a separate follow-up because the planner's
reuse proof can resolve a deferred classifier from required discovery material.
Operation tags and physical encoder metadata remain until their consumers are
fully audited.

No tests were executed here. Python syntax, whitespace, local test-file targets,
and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10c-dsl-crossmatch
recipe_bundle="$HOME/Downloads/recipes-10c-dsl-crossmatch.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_crossmatch_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_ir_integration.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_crossmatch_capability.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Validate DSL catalog requirements through crossmatch recipes" \
  --body 'Route explicit and implied catalog requirements through the lowered GetCrossmatch operation and shared IR resolver. Reject catalogs available only on other endpoints and unusable owned target bindings. Preserve qualified labels while scoping report evidence to eligible retrievals. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared yet, rerun the final command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
