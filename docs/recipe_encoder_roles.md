# Shared physical encoder operands (branch 10m)

Branch: `refactor/recipes-10m-encoder-roles`, based on merged `main` at
`7065d98` (PR #285).

After recipe-owned operation-tag removal, the remaining physical declarations
still serve active consumers. bind and binding.roles identify encoder operands,
collection cardinality, and target identity. Unowned operations still use shared
compatibility routing. They remain in place.

The recipe compiler and binder independently checked the same direct/composite
operand contract. Move that reader to binding_roles in the generic request
transform layer. It preserves declared operand order, rejects malformed or
conflicting roles, and reads no semantic intent. Recipe source paths still belong
to compiled calls; legacy plans still resolve existing endpoint roles. Composite
adapter validation, scalar/collection encoding, and physical type coercion keep
their existing owners.

The compiler wraps reader failures in RecipeRegistryError with declaration
context; graph construction continues to expose CapabilityGraphError. Binding
wraps the same failures in ParameterBindingError. A malformed, non-mapping binding
container now produces that public binder error instead of AttributeError.
Existing invalid-bind/invalid-encoder compiler diagnostic prefixes are preserved.
Graph role indexing and mapping-schema validation retain their separate purposes.

Regression cases compare rejection of malformed operand declarations through
recipe compilation, legacy binding, and explicit recipe binding. Existing tests
cover valid scalar, collection, SQL membership, and native composite encoders.
Add the generic request-transform contracts to registry CI and make DSL CI watch
the request-transform package, since recipe compilation and binding consume it.

Provider YAML, recipe resolution, semantic mappings, executor behavior, and
normalization remain unchanged. The central legacy broker registry and its public
compatibility import remain untouched. No tests were run here; Python syntax,
workflow YAML, declaration invariance, whitespace, local test paths, handoff shell
syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10m-encoder-roles
recipe_bundle="$HOME/Downloads/recipes-10m-encoder-roles.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_request_transforms.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_spatial_binding.py \
  tests/test_orchestration_antares_cone_binding.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_orchestration_photometry_recipes.py \
  tests/test_orchestration_predicate_recipes.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Share physical encoder operand validation" \
  --body 'Use one generic reader for bind/binding.roles in recipe compilation and physical binding. Preserve operand order, encoder behavior, and public error families; report malformed binding containers as ParameterBindingError. Cover compiler and both binding paths with shared malformed-contract regressions and update CI coverage. Provider declarations are unchanged. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
