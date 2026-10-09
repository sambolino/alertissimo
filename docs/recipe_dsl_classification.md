# Shared DSL classification evidence (branch 10e)

Branch: `refactor/recipes-10e-dsl-classification`, based on merged `main` at
`01028b6` (PR #277).

DSL classification checks previously accepted mapped classification families and
classifier parameter names independently of retrieval recipes. This could bypass
an unusable owned target binding or accept a qualified selector after a filter
had changed the candidate population. Fresh-call validation alone would also
reject valid ALeRCE discovery workflows that already supply qualified material.

Explicit and implied classification requirements now lower their actual Get
operation and consume `validate_step_capabilities`. When that request is deferred,
`classification_material_capabilities` may prove support from required discovery
material using the emitted retrieval's real canonical prefix. The DSL's independent
classifier-parameter shortcut is removed. Unowned provider compatibility remains
in the shared IR resolver.

The existing pure full-script and continuation lowering loops now support stopping
before an emitted requirement. Regular compilation uses those same loops, so the
validator does not maintain another operation-order implementation. Full scripts
preserve candidate predicate scope, implicit/explicit deduplication, and intervening
filters. Continuations preserve the actual base WorkflowIR, its selection and
population barriers, and existing requirement deduplication. An unrelated later
lowering failure cannot erase proof for an earlier occurrence. No endpoint selection
or physical execution occurs in capability validation.

Supported checks retain qualified labels scoped to eligible retrievals or the
required discovery owner. A failed material proof leaves the fresh-call diagnostic
and no eligible evidence. The report schema, source constraints, clause metadata,
local method handling, ontology gates, and presentation intent remain intact.
Provider declarations, normalization, and execution ownership are unchanged.

Regression coverage includes fresh statuses, explicit/implied discovery proof,
filter barriers, later lowering failures, tag-free recipes, unusable owned bindings,
and continuation context and deduplication. No tests were run here. Python syntax,
whitespace, local test targets, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10e-dsl-classification
recipe_bundle="$HOME/Downloads/recipes-10e-dsl-classification.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_public_api.py \
  tests/test_dsl_ir_integration.py \
  tests/test_orchestration_classification_material.py \
  tests/test_orchestration_recipe_reuse.py \
  tests/test_orchestration_planner.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Validate DSL classification through recipes and discovery material" \
  --body 'Replace independent DSL classification eligibility with lowered Get validation and shared required-discovery material proof. Use actual compiler prefixes and continuation WorkflowIR context, preserving occurrence order, deduplication, filter/selection barriers, source metadata, and qualified evidence. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared yet, rerun the final command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
