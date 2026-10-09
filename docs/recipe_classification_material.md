# Shared classification material proof (branch 10d)

Branch: `refactor/recipes-10d-classification-material`, based on merged `main` at
`ca6a519` (PR #276).

A qualified classification Get can be deferred as a fresh provider request while
an earlier discovery execution already supplies the requested material. The
planner has a narrow proof for this case. Moving DSL classification checks directly
to fresh-call validation would reject valid ALeRCE workflows; duplicating the
planner's proof in the DSL would create another routing implementation.

`classification_material_capabilities` now exposes the semantic part of this proof
through the read-only orchestration capability bridge. It accepts the retrieval,
its earlier canonical Steps, and the graph. Evidence identifies the discovery
owner index, source, endpoint, and compiled dynamic classification record types.
An empty tuple means an owner cannot be established for every requested source.
The check neither selects among alternatives nor builds physical plans.

The proof retains the existing boundaries: positive producer-qualified predicates,
explicit broker/origin constraints, a supported target-bound unqualified retrieval
recipe, uniquely resolvable discovery, required mapped material, no cross-call
identity dependency, and no competing discovery constants. Lookup-only owners,
changed populations, global latest selection, explicit consumer targets, OR/NOT
references, and ambiguous alternatives do not supply this proof. Legacy discovery
inspection remains available only for operation/source pairs without recipes.

The planner consumes this capability evidence and retains its concrete selected-call
check, request-constant comparison, and execution ownership marking. Optional
material still cannot satisfy a mandatory retrieval. Retrieval-material intent now
lives in the capability bridge; the existing positive-reference rule lives beside
IR predicates. These rules are shared rather than duplicated.

This branch prepares the classification DSL cutover. Its existing shortcut remains
until the next small branch supplies the actual lowered workflow prefix to the
shared proof. No provider declarations, IR vocabulary, execution, or normalization
responsibilities change.

No tests were run here. Python syntax, whitespace, local test targets, and bundle
structure were checked. Regressions cover eligible discovery reuse, intervening
retrievals, population/selection/source barriers, constants, compiled outputs,
ambiguity, and positive qualifier semantics.

## Local handoff

```bash
recipe_branch=refactor/recipes-10d-classification-material
recipe_bundle="$HOME/Downloads/recipes-10d-classification-material.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_classification_material.py \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_lightcurve_forced_reuse.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_ir_models.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Share qualified classification discovery-material proof" \
  --body 'Expose read-only capability evidence for qualified classification material from uniquely proven required discovery calls. Share retrieval intent and positive predicate semantics, and make planning consume the proof while retaining concrete call and execution ownership checks. Prepare the DSL classification cutover without changing provider declarations. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared yet, rerun the final command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
