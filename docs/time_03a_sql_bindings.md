# Bind SQL time windows alongside numeric discovery predicates

Based on merged Time 02 PR #307, main `5840d31`. This is the first small part
of Time 03. Production provider declarations remain unchanged; Lasair ZTF
activation follows separately in Time 03b.

## Problem and resulting behavior

The same physical SQL `conditions` parameter can carry an object-ID membership
query, a numeric discovery predicate, or a time-window condition. The existing
target-ID encoder must remain valid for identity-bound summary supplements.
Assigning a window must not overwrite an explicit scientific predicate.

A physical string parameter can now declare an alternate whole-TimeContext
encoder in its existing binding metadata. A **test-only** example is:

```yaml
conditions:
  type: string
  bind: target_id
  binding:
    collection: adapter
    max_items: 100
    adapter: alertissimo.data_layer.transforms.sql:string_membership_condition
    adapter_options:
      column: objects.objectId
      value_pattern: '^ZTF\d{2}[a-z]{7}$'
    time_context:
      adapter: alertissimo.data_layer.transforms.sql:time_window_condition
      adapter_options:
        first_column: objects.jdmin
        last_column: objects.jdmax
        subtract: 2400000.5
        order_by: objects.objectId
```

Only a recipe's explicit `conditions: {from: step.time_context}` selects that
alternate. Object-ID dependencies continue through their ordinary encoder,
including the current batch limit and fixed supplement pagination. Selection
never depends on user text, a parameter's value shape, or the broker name.

The existing binder resolves the entire TimeContext against its pinned clock.
A pure registered transform encodes the resolved bounds as numeric SQL:

| Mode | Encoded condition, before ordering |
| --- | --- |
| default detection | `last_mjd >= start AND first_mjd <= end` |
| first | `first_mjd >= start AND first_mjd <= end` |
| last | `last_mjd >= start AND last_mjd <= end` |

The raw column subtraction is identical to the declared response transform:
for JD columns, compare `(column - 2400000.5)` to the canonical UTC MJD bound.
Do not round a bound through a reverse JD addition. Endpoints are inclusive.
No UTC-to-TAI conversion or other survey's schema is inferred.

Default detection mode is **only a safe summary-overlap prefilter**. A candidate
with observations on either side of a historical gap deliberately survives this
SQL condition. Its separate required detection-evidence call must establish
actual membership before it can become a selected result.

If a supported numeric predicate also addresses `conditions`, the binder joins
the two compiled WHERE fragments with AND and emits one shared ORDER BY.
Different/missing orderings fail explicitly. Unsupported operators, values,
qualifiers, OR, or partially translated predicates still defer even when the
window could supply a physical condition on its own.

## Registry and architecture boundaries

The compiler checks that the time columns, subtraction, and identity ordering
match the call's mapped numeric predicate declarations for both inclusive
operators. Existing constant projection, single-table, automatic pagination,
and physical assignment conflict checks remain active. A temporal proof is
required; overlap alone cannot be declared as native detection membership.
Runtime input cannot replace the compiled TimeContext or semantic predicate.

All work stays in the existing recipe compiler, request transforms, binder, and
capability validation. No new IR Step, service, architecture layer, dependency,
generic SQL engine, or public syntax is introduced. There are no production
provider YAML changes in this PR.

## Why activation is a separate branch

The pinned Lasair implementation returns detections and upper limits together
in its candidates array. Its lightcurve serializer can also return per-object
error rows. Time 03b must handle these evidence details before enabling default
within, as well as the required summary evidence for first/last cone selection.
The current source inspection is not a declaration that the mixed array is
already a valid detection-only witness. Global latest remains in the scheduled
shared/provider selection milestones.

The source audit used the official
[Lasair implementation at `2b940d4`](https://github.com/lsst-uk/lasair4/tree/2b940d41c456545164c587e0f053e6312c2d105a):
`webserver/lasairapi/serializers.py` accepts selected/tables/conditions and
appends limit/offset separately; `webserver/lasair/lightcurves.py` reads both
candidates and noncandidates; `common/schema/objects.py` describes the summary
date columns. No upstream client or broker request was executed here.

## Local verification handoff

No tests, builds, project imports, apps, or live broker calls ran here. Python
AST, Git whitespace, and bundle checks are the offline verification.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_sql_time_bindings.py \
  tests/test_lasair_semantic_search.py \
  tests/test_discovery_time_bindings.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_request_transforms.py
```

The new module is included by the existing DSL CI orchestration glob. Its
temporary provider copies are synthetic contracts, not activation. SQLite
independently evaluates all three window encodings and conjunction with numeric
predicates. Cases also cover JSON plan round trips, absolute/relative timezone
equivalence, no clock sampling during planning, the unchanged ID encoder,
runtime override rejection, invalid column/unit/projection/proof declarations,
and explicit deferral for untranslated predicates. A production-graph assertion
keeps Lasair time windows deferred until Time 03b.
