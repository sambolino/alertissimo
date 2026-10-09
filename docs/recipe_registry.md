# Provider recipe registry (branch 02)

Branch 03 now activates atomic cone declarations; see `recipe_atomic_cone.md`.
Branch 04 activates discovery-dependent cone follow-ups; see `recipe_composite_cone.md`.
Branch 05 activates lightcurve and internal forced-photometry retrievals; see `recipe_lightcurves.md`.
Branch 06a activates object lookup recipes with an explicit input namespace; see `recipe_lookup.md`.
Branch 06b activates targeted classification retrievals; see `recipe_classification.md`.
Branch 06c activates targeted crossmatch retrievals; see `recipe_crossmatch.md`.
Branch 06d declares product retrievals and validates their activation boundaries; see `recipe_products.md`.
Branch 07 compiles endpoint predicate bindings and scopes them to discovery calls;
see `recipe_predicates.md`.
Branch 08 activates the first verified latest-selection contract and global
candidate reduction; see `recipe_selection.md`.
Branch 09a activates ALeRCE semantic-search recipes through the shared discovery
resolver; see `recipe_semantic_search.md`.
Branch 09b supplies confirmation evidence through provider recipes and endpoint-local
field mappings; see `recipe_confirmation.md`.
In the current schema, `target_kind` is required for lookup, cutout, and data-product
recipes. It guards the existing IR target namespace; other operations reject it.
The foundation described below was introduced in branch 02 before activation.

Provider recipes live in
`alertissimo/data_layer/providers/<broker>/<origin>/capabilities.yaml`.
The file is optional during migration. The older central broker capabilities
file is unchanged and is not a recipe file.

`build_capability_graph()` loads present recipe files after endpoint and mapping
evidence has been compiled. `graph.query_recipes(broker=..., origin=..., op=...)`
returns matching declarations. This branch does not change planner selection,
binding, execution, normalization, or existing endpoint tags. No production
provider recipes are installed yet; the regression fixtures use actual provider
contracts in temporary directories.

## Authored structure

```yaml
broker: lasair
origin: ztf
recipes:
  cone_search:
    - calls:
        - endpoint: cone
          params:
            ra: {from: step.ra}
            dec: {from: step.dec}
            radius: {from: step.radius}
        - endpoint: query
          required: false
          params:
            conditions:
              from: {call: 0, path: summary.identity.object_id}
            selected:
              value: objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax
            tables: {value: objects}
            limit: {value: 100}
            offset: {value: 0}
```

`recipes` is keyed by exact existing IR `op` discriminators, obtained from
`StepUnion`. Each operation contains a non-empty list of alternatives, each with
a non-empty `calls` list. Alternatives have no authored capability IDs, priorities,
or scores. Their indexes identify declarations for diagnostics, not preference.
Future planning must reject unresolved ambiguity rather than choose list order.

Top-level `description`, `predicate_bindings`, and `selection_bindings` are optional. Other top-level keys
are rejected. A recipe contains `calls` and, for targeted lookup/product operations,
`target_kind`. Each call accepts only `endpoint`, `params`, and `required`.
`endpoint` is required; `params` defaults to an empty mapping and `required`
defaults to true. At least one call must be required.

Every parameter assignment has exactly one of these forms:

| Form | Meaning |
| --- | --- |
| `{from: step.ra}` | Value of an actual field on the concrete IR model |
| `{from: step.target.ids}` | Target collection; explicit or late-bound behavior is preserved by later planner/binder work |
| `{from: {call: 0, path: summary.identity.object_id}}` | Candidate identities from an earlier call in the same recipe |
| `{from: {ra: step.ra, dec: step.dec}}` | Named operands of the parameter's existing physical encoder |
| `{value: 100}` | Already-physical constant |

Direct paths are checked against Pydantic IR model fields. Nested optional models
are traversable; list/dict indexing, computed expressions, and arbitrary attribute
access are rejected. This is structural validation, not proof that an optional
field is supplied in a particular workflow. Concrete feasibility remains a
planner responsibility.

The named-input form covers ANTARES without putting an adapter into the recipe:

```yaml
broker: antares
origin: ztf
recipes:
  cone_search:
    - calls:
        - endpoint: cone_search
          params:
            center:
              from: {ra: step.ra, dec: step.dec}
            radius: {from: step.radius}
```

The `center` parameter's endpoint declaration already supplies its registered
SkyCoord adapter and `[ra, dec]` operands. The recipe's operand keys must match
those declarations exactly. Registered callable signatures are inspected for
operand/option compatibility; adapters are never invoked while loading. Astropy
therefore remains lazy. Existing scalar, CSV, and adapter collection contracts,
including positive batch limits, are retained.

Constants are validated against declared physical types and enums. They must be
finite JSON-compatible values and are frozen internally, including nested
collections. They are physical values, not inputs to an adapter. Consumer code
must materialize frozen collections when building a request. Workflow-dependent
conversion and supplied-value coercion remain binder responsibilities.

Required physical parameters need an explicit assignment, a non-null endpoint
default, or a fixed transport value. Provider and endpoint fixed transport values
are combined using the existing override precedence. A recipe cannot override
them with a conflicting value or dynamic source.

## Dependency limits

Call references are zero-based and must point backwards. The only supported
semantic dependency is `summary.identity.object_id`, and the referenced endpoint
must actually map that field. The destination must use the existing `target_id`
binding contract. One call may have only one candidate owner. A required call
cannot depend on an optional call. These restrictions match the current staged
runtime; loading does not imply generic arbitrary-output binding support.

Each compiled `RecipeCall.outputs` retains endpoint-specific qualified field
mapping objects, including raw field and payload identity. Optional call outputs
are not promoted into required output evidence. Mappings describe possible
outputs, not guaranteed non-null data or proof that a SQL projection/response
mode includes every mapped field. Concrete projection compatibility, semantic
record matching, residual coverage, batching, identity consolidation, and selection
safety are subsequent planning checks.

Missing recipe files preserve legacy graph behavior. Invalid declarations raise
`CapabilityGraphError` with the file and declaration location. Duplicate YAML
keys, unknown fields, orphan recipe files, unknown operations/endpoints/parameters,
and invalid dependencies fail visibly. Predicate declarations use the endpoint-local
shape documented in `recipe_predicates.md`. Selection declarations and their
current activation bounds are documented in `recipe_selection.md`.

## Local handoff

Branch: `refactor/recipes-02-registry`. This branch currently builds on the prepared
branch-01 commit because that commit was not yet on remote `main` when work began.
The bundle contains both commits. Merge branch 01 first, then import and rebase
this branch onto updated `main`; Git can skip the already-applied foundation.

```bash
recipe_branch=refactor/recipes-02-registry
recipe_bundle="$HOME/Downloads/recipes-02-registry.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main

git diff --check origin/main...HEAD
PYTHONPATH=. python -m pytest -q \
  tests/test_recipe_registry.py tests/test_capability_graph.py
```

Tests were not run in the editing environment. After these commands pass:

```bash
git push -u origin "$recipe_branch"

recipe_pr_body=$(mktemp)
cat > "$recipe_pr_body" <<'EOF'
Compile optional provider-local recipes into CapabilityGraph without activating them in the planner. Validate references against existing IR models, endpoint signatures, encoders, and endpoint-specific mapping evidence; preserve per-call required/optional boundaries and reject invalid dependency wiring.

Support direct fields, physical constants, existing named encoder operands, and earlier-call candidate identity. Keep existing providers and execution behavior unchanged, and add the recipe contract suite to CI.

Validation: run the focused recipe-registry and capability-graph tests locally before submission. Tests were not run in the editing environment.
EOF
gh pr create --base main --head "$recipe_branch" \
  --title "Compile validated provider recipes into the capability graph" \
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

The existing `setup.py` provider YAML pattern and `MANIFEST.in` recursive provider
rule already include these new filenames. Python modules are included by the
existing package discovery. Both focused workflows now run the recipe suite, and
the DSL workflow watches the new loader and provider recipe files.
