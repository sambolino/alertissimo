# Shared DSL retrieval validation (branch 10b)

Branch: `refactor/recipes-10b-dsl-retrievals`, based on merged `main` at
`56c18ec` (PR #274).

DSL requirement validation previously treated mapped record families or selected
operation tags as sufficient retrieval evidence. For example, a Fink ZTF
`with data_product` requirement could report support from `data_product_lookup`
even though the selected product recipe lacked verified response-mode mappings.
A lightcurve recipe that no longer bound candidate identities could likewise
remain supported through its endpoint's record-family mapping.

Lightcurve and data-product requirements now use the pure `_lower_requirement`
helper and `validate_step_capabilities`, matching the Get operation that compilation
emits. The existing cutout lowering rule uses this route when the supplied
ontology admits that noun. Production ontology validation is unchanged: artifacts
remain `data_product`, and standalone `cutout`/`forced_photometry` nouns are not
added by this branch.

Checks preserve clause location, requested origin, effective broker/channel,
semantic noun, and per-source IR diagnostics and eligible endpoint evidence.
A producer or product detail that the Get IR cannot preserve becomes a deferred
check with the lowering diagnostic. Local method requirements retain their
existing deferral. The independent DSL operation-fallback table and function are
removed. Compatibility for unowned operation/source pairs belongs to the shared
IR resolver.

Classification and crossmatch requirement checks remain for a separate branch:
qualified discovery material can satisfy a later retrieval, so that audit must
include workflow context rather than validating a fresh call alone. Provider
operation tags and physical binding metadata remain until their consumers are
resolved. This branch changes no execution, normalization, recipe declarations,
selection, or local derivation behavior.

Regression coverage includes production statuses, broker overrides across origins,
recipe support without tags, an unusable owned recipe with legacy evidence still
present, a verified JSON product contract, and unrepresentable requirement details.
No tests were run here. Python syntax, whitespace, test-file targets, and bundle
structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10b-dsl-retrievals
recipe_bundle="$HOME/Downloads/recipes-10b-dsl-retrievals.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_retrieval_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_lightcurve_forced_default.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_lookup_pipeline.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_product_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Validate DSL retrieval requirements through shared IR recipes" \
  --body 'Validate lightcurve and product requirements using the same lowered Get operations and per-source recipe evidence as planning. Remove the DSL operation fallback, reject unusable owned recipes and unrepresentable details, and preserve ontology gates and source metadata. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the final command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
