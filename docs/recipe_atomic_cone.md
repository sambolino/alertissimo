# Atomic cone recipe activation (branch 03)

`refactor/recipes-03-atomic-cone` activates provider recipes for ConeSearchStep.
The exact existing `cone_search` discriminator selects declarations. Required
call mappings must cover the requested record family. Recipes supply input paths;
the binder still owns physical encoding and the executor still runs one call.

Eight broker/survey paths now have a single-call recipe:

| Broker | Origins | Endpoint |
| --- | --- | --- |
| ALeRCE | LSST, ZTF | `query_objects` |
| ANTARES | LSST, ZTF | `cone_search` |
| Fink | LSST, ZTF | `conesearch` |
| Lasair | LSST, ZTF | `cone` |

The ALeRCE catalog-cone and Fink skymap endpoints have no mapped output evidence
that makes them eligible for this migration. No additional support is claimed.

IR capability validation retains matching recipe alternatives alongside endpoint
evidence. The planner uses those same alternatives, so two recipes targeting the
same endpoint remain ambiguous. A migrated provider never falls back to its old
tags when a recipe cannot satisfy the request. Providers with no recipe for this
operation can still use the legacy bridge during the transition.

All three canonical cone coordinates must appear as recipe source paths. Supplied
`magnitude_limit` and `time_context` need a declared translation; non-empty legacy
`criteria` remain deferred. These currently unimplemented constraints are no longer
silently dropped on migrated cone plans. Error messages include source-specific
reasons. This branch does not implement `latest` selection or selection pushdown;
that remains branch 08 work. Predicate realization uses the existing request
mapping mechanism, unchanged.

## Runtime binding

`EndpointPlan.parameter_sources` contains only compiled IR field paths:

```python
# Scalar physical parameters:
{
    "ra": ("ra",),
    "dec": ("dec",),
    "radius": ("radius",),
}

# ANTARES's existing encoder operands:
{
    "center": {"ra": ("ra",), "dec": ("dec",)},
    "radius": ("radius",),
}
```

`None` selects legacy endpoint-role assignment. A recipe mapping, including an
empty one, is authoritative: the binder does not add semantic assignments from
legacy `bind` fields. Those fields still describe encoder operands during the
migration. Both paths use the same physical collection/adapter/coercion helpers.

Constants compile to `request_params`; frozen literal collections are materialized
before reaching the binder. Primitive physical coercion now also accepts declared
boolean, dict, and array values so valid recipe constants can be represented.
No encoders run during planning. Runtime JSON round trips retain compiled paths.

The recipe graph stays internal; compiled source paths never enter WorkflowIR.
Defaults, headers, authentication, transport, units, and response mappings remain
on their current contracts.

## Migration boundary

Lasair/ZTF still appends its existing optional compact summary plan after the
recipe-selected cone call. Its batching, failure behavior, and one-Step ownership
are unchanged. Branch 04 will move that dependency and its constants into the
recipe. Multi-call recipes are still explicitly deferred in this branch.

Other IR operations remain on their existing paths. The older DSL surface
capability report still uses its broad tag-based checks; consolidating that bridge
is part of the later cutover. Tags and legacy endpoint bindings are therefore
retained in this branch even though active IR cone planning and scalar source
assignment no longer require them.

The branch-02 loader tests now remove any copied production recipe before authoring
their fixture declaration, so the tests continue to cover missing-file fallback
independently of how many provider operations have migrated.

## Local commands

Remote `main` was still at `18713d4` when this branch was prepared. The bundle
includes branches 01 and 02 as dependencies. Merge those branches in order first;
then import this branch and rebase onto updated `main`.

```bash
recipe_branch=refactor/recipes-03-atomic-cone
recipe_bundle="$HOME/Downloads/recipes-03-atomic-cone.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main

git diff --check origin/main...HEAD
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_cone_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_spatial_binding.py \
  tests/test_orchestration_antares_cone_binding.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_lasair_ztf_compact_cone_summary.py \
  tests/test_request_transforms.py
```

Only syntax and diff checks were performed in the editing environment. Tests are
for the local machine. After they pass:

```bash
git push -u origin "$recipe_branch"

recipe_pr_body=$(mktemp)
cat > "$recipe_pr_body" <<'EOF'
Activate single-call cone recipes for ALeRCE, ANTARES, Fink, and Lasair across ZTF and LSST. IR capability validation and planning use the same recipe alternatives, while compiled field sources reach the existing binder and physical encoders.

Preserve Lasair's optional summary supplement and all non-cone planning paths. Migrated providers cannot silently fall back to tags when recipe matching fails; undeclared time, magnitude, and legacy criteria inputs defer with an explicit reason. Equal alternatives remain ambiguous.

Validation: run the focused cone, loader, binding, planner, compact-summary, and transform suites locally before submission. Tests were not run in the editing environment.
EOF
gh pr create --base main --head "$recipe_branch" \
  --title "Activate provider recipes for atomic cone planning" \
  --body-file "$recipe_pr_body"
rm "$recipe_pr_body"
```

After review and passing checks:

```bash
gh pr checks "$recipe_branch" --watch
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
