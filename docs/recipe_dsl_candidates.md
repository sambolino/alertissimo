# Shared DSL candidate resolution (branch 09f)

Branch: `refactor/recipes-09f-dsl-candidates`, based on `main` at `8d695d3`
(PR #272).

DSL candidate validation previously accepted any endpoint mapping summary records
for generic discovery, used separate spatial operation tags for cones, and
duplicated lookup cardinality routing. This could report support for a request
that recipe validation and planning subsequently rejected. It also rejected
valid lookup/cone recipes when their migrated operation tags were removed.

Candidate checks now use the existing pure `_candidate_operation` lowering helper
and `validate_step_capabilities`. The resulting Lookup, ConeSearch, or
SemanticSearch operation is the same first step emitted by compilation, including
predicate scope, time context, latest selection, target namespace, and sources.
No endpoint selection, physical binding, or provider execution occurs during
validation.

Each requested source retains its own check with the IR status and diagnostic,
requested broker/origin constraints, canonical record noun, and eligible endpoint
evidence. Owned recipes establish eligibility even without operation tags; an
unusable owned recipe cannot fall back to summary presence or legacy tags. Fink
and ANTARES generic discovery now reports the 09e deferral during DSL validation,
while executable cone and lookup requests remain supported. Lasair generic
semantic discovery remains unsupported. Lowering failures are reported as
deferred candidate checks with their original message and clause location.

The public report schema and separate selection checks remain in place.
Requirement evidence, confirmation quorum, fragment handling, execution,
normalization, and IR vocabulary retain their existing responsibilities.
Synthetic requirement-test endpoints now declare generic discovery explicitly,
so those cases continue testing requirement qualifiers rather than relying on
the removed summary-presence shortcut. Candidate regressions cover real-provider
statuses, wildcard and per-origin checks, compiled calls without tags, unusable
owned declarations, and an ambiguous angle-unit diagnostic.

The next stage is the consumer audit and compatibility cleanup from branch 10.

## Local handoff

No tests were run here. Python syntax, whitespace, and bundle structure were
checked.

```bash
recipe_branch=refactor/recipes-09f-dsl-candidates
recipe_bundle="$HOME/Downloads/recipes-09f-dsl-candidates.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_candidate_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_ir_integration.py \
  tests/test_dsl_lookup_pipeline.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_public_api.py \
  tests/test_dsl_live_material_lineage_matrix.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_cone_recipes.py

git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Resolve DSL candidates through the shared recipe validator" \
  --body 'Validate the same lowered Lookup, ConeSearch, and SemanticSearch operations used by compilation. Replace duplicated DSL candidate routing with per-source IR recipe evidence and diagnostics, preserving report metadata and selection checks. Reject unusable owned declarations and support valid recipes without legacy operation tags. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks are reported yet, rerun the final command once workflows appear.
After review and successful checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
