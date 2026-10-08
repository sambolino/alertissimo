# Product recipe boundaries (branch 06d)

Branch: `refactor/recipes-06d-products`.
Base: `main` at `b1ed477` (PR #264).

This increment declares `get_cutout` and `get_data_product` on the four
ALeRCE/Fink provider paths that previously advertised those operations through
tags. Auditing the actual contracts found that their production normalization
evidence is incomplete. These requests now fail visibly as deferred, instead of
being advertised as supported and later failing binding or producing no mapped
product material. No new scientific fields or response decoding are invented.

| Provider | Declared calls | Input namespace | Current activation boundary |
| --- | --- | --- | --- |
| ALeRCE/ZTF | `get_stamps`; also `get_avro` for generic products | Object | No mapped `data_product` fields |
| ALeRCE/LSST | `get_stamps` | Object | No mapped `data_product` fields; disabled AVRO call is excluded |
| Fink/ZTF | `cutouts` | Object | Image/array response modes lack compatible named-field mapping evidence |
| Fink/LSST | `cutouts` | Alert | Existing normalization cannot use an alert ID as ownership proof for an object Portfolio; response-mode evidence is also incomplete |

The existing `target_kind` guard now applies to product recipes as well as
lookup. It is required, checked against the actual operation's IR model, and must
be explicit. Other operations still reject it. It distinguishes `objectId` from
`diaSourceId` without deriving the input namespace from mapped output families:

```yaml
get_cutout:
  - target_kind: alert
    calls:
      - endpoint: cutouts
        params:
          diaSourceId: {from: step.target.ids}
          kind: {value: All}
          output-format: {value: array}
```

The Fink declarations explicitly request the documented all-cutout array mode;
this call assignment is not treated as proof that the existing response mappings
cover it. Object IDs and implicit candidate IDs cannot enter the LSST alert
recipe. An explicit target without a namespace is deferred. A targetless product
recipe can consume only the existing staged summary object-ID population.

The physical `target_id` encoder role is added to the existing object/source ID
parameters. Their types and cardinality remain unchanged. Scalar fan-out and
ALeRCE integer coercion use existing binding. The disabled ALeRCE/LSST AVRO path
is not authored. No endpoint is enabled or new physical parameter added.

`CapabilityGraph` now retains physical parameters already labeled
`role: output_format`. Fink cutout output-format controls receive that existing
role. Product feasibility requires mapped product fields and a declared JSON
object/array response without an unresolved output-format control. A default,
recipe constant, or nominal output label cannot establish response compatibility.
Multiple formats need verified mode-specific evidence before activation.

Requested cutout format/size and generic product type remain deferred until their
translation and response/selector compatibility are established. They are never
silently discarded. In particular, mapping a possible `data_product.type` field
does not prove a physical call retrieves a requested product type.

The current normalizer can complete summary object identity from a physical
`target_id`. That is appropriate for an object input and unsafe for an alert
input. Alert product activation therefore remains deferred until its ownership
contract is established, even if a response can otherwise be parsed as JSON.
No normalizer behavior is changed in this branch.

A synthetic JSON-product fixture covers the supported boundary using existing
ontology fields. It exercises ordinary planning, scalar fan-out, canonical
normalization, and current candidate IDs after a Filter. Recipe target inputs
now retain candidate dependencies even when no earlier execution-reuse proof
exists, which is necessary for cutouts. It does not enable reuse or change the
executor. Legacy providers without a product recipe retain their compatibility
path during migration.

Production support is intentionally not claimed. Enabling these product paths
requires actual response captures, correct mode-specific mappings/decoding, and
alert ownership evidence where applicable. That work is separate from replacing
the recipe registry and must not be hidden by legacy fallback. Spectra remain
unsupported because no registered spectrum retrieval exists.

## Local workflow

Download `recipes-06d-products.bundle`, then run in the repository with your
virtual environment active:

```bash
recipe_branch=refactor/recipes-06d-products
recipe_bundle="$HOME/Downloads/recipes-06d-products.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_product_recipes.py \
  tests/test_orchestration_lookup_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_capability_graph.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_normalization.py \
  tests/test_fink_registry_architecture.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Declare product recipe contracts and defer incomplete evidence" \
  --body 'Declares cutout and data-product recipes with explicit object/alert input namespaces. Compiles existing output-format controls and defers requests lacking mapped material, compatible response modes, or alert ownership evidence. Preserves existing binding and adds candidate flow for verified product recipes. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared immediately after pushing, rerun the watch command
once GitHub queues them. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

Author-side inspection: Python/YAML syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent. Next increment: branch 07,
relocating existing predicate bindings with their explicit operators.
