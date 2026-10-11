# Recipe runtime

This guide describes the active recipe system after the migration. Historical
branch runbooks remain in `recipe_system_overhaul.md` and its companion files.

## Declaration ownership

| Declaration | Owns |
| --- | --- |
| WorkflowIR models | Existing Step.op values, inputs, predicates, selections, and lifecycle intent |
| Scientific ontology | Record families, fields, and producer/channel qualifiers |
| Provider endpoints.yaml | Physical parameters, transports, defaults, value types, encoder operands, and collection limits |
| Provider mappings.yaml | Payload paths, normalized scientific fields, transforms, and identity partitions |
| Provider capabilities.yaml | Ordered call recipes and explicit predicate/selection translations |
| CapabilityGraph | Immutable compiled evidence from those declarations |

Provider files live under
`alertissimo/data_layer/providers/<broker>/<origin>/`. The older central
`data_layer/runtime/capabilities.yaml` is exposed by a legacy compatibility import;
it is separate from provider recipes and does not drive CapabilityGraph.

`build_capability_graph()` loads endpoint-local mapping evidence before compiling
recipes. `graph.query_recipes(broker=..., origin=..., op=...)` inspects declarations;
it does not select a call or prove that a particular request is executable.

## Recipes and physical encoding

Recipes use exact IR operation discriminators. Each operation contains alternatives;
each alternative contains ordered physical calls. For example, the Lasair ZTF
cone recipe discovers IDs and optionally retrieves their compact summaries:

```yaml
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

Parameter assignments contain exactly one of from or value. Direct sources read
actual fields on the operation's IR model. Named input mappings supply operands
to an existing physical encoder, such as ANTARES's center parameter. Cross-call
references currently support only normalized summary.identity.object_id from an
earlier required call. Constants are finite JSON-compatible physical values.
Lookup, cutout, and data-product recipes declare target_kind from the IR target
namespace. Other operations reject that key.

bind and binding.roles remain physical contracts. The generic binding_roles
reader checks their operand declarations for recipe compilation and binding.
Recipes provide semantic source assignments; the binder applies existing scalar,
collection, SQL-membership, and native-value encoders. Parameter defaults and
transport fixed parameters retain their physical ownership.

No expression language, arbitrary attribute access, provider adapter dispatch,
recipe scores, or YAML-order tie-breaking is supported. Equally feasible
alternatives remain ambiguous.

## Predicate and selection evidence

predicate_bindings connects an endpoint-local mapped scientific path and an
explicit IR comparison operator to a physical request parameter. A fixed
probability threshold declared for >= consumes only that operator. Its name does
not imply a comparison. Other operators remain residual only when normalized
material can evaluate them; absent fields cannot become residual evidence.

Bindings belong to the candidate discovery call. A later enrichment call cannot
prune the discovery population. Conjunction pushdown preserves a candidate
superset; existing OR, NOT, conflicting-value, and qualifier restrictions remain.

selection_bindings currently declares the verified ALeRCE ZTF recency ordering.
Latest selection remains global after complete discovery pagination, residual
pruning, and object consolidation. A page or dependency batch limit is not a
global latest-N result. Unproven ordering or untranslated criteria defer.

## Validation, planning, and execution

DSL checks lower the same canonical operations that compilation emits. Shared
IR validation resolves per-source recipe feasibility and exposes supported,
deferred, or unsupported results with reasons. Mapping evidence stays local to
the selected endpoint and retains producer/channel qualifiers. Possible mapped
fields do not prove non-null payload values or a particular response projection.

Planning selects from the same evidence, expands ordered calls into EndpointPlan
objects, and records source assignments, candidate dependencies, optionality, and
proven execution reuse. A declaration may compile correctly while a concrete
request remains deferred, unsupported, or ambiguous.

For an operation/source pair with recipes, the owned resolver remains authoritative
even when no alternative can satisfy the request. It never falls back to endpoint
tags or unrelated family mappings. A pair without recipes retains the shared
compatibility resolver. Remaining operation_types therefore serve unowned paths
or mixed metadata; they are not proof for an owned operation.

The binder resolves explicit or runtime values without copying candidate IDs
into WorkflowIR. The executor invokes bound physical calls; normalization reads
payloads through mappings. Staged orchestration keeps one semantic Step across
multiple physical calls, batching, optional failures, sparse execution alignment,
provenance, continuation, and vacuous empty candidate dependencies.

Confirmation recipes supply evidence and lookup/history tiers. Orchestration
still owns quorum and candidate reduction. Optional calls cannot supply the sole
proof for mandatory fields, selection keys, or later bindings.

Execution reuse requires a matching selected required physical call and compatible
mapped material. For dynamic classifier-qualified material, the shared proof
requires unchanged discovery context, an explicit positive producer predicate,
and a unique required discovery owner for every constrained source. Filters,
selection, conflicting constants, and ambiguous ownership invalidate that proof.
Fresh ALeRCE LSST classifier-qualified retrieval remains deferred without it.

## Current provider scope

All eight broker/survey pairs author cone_search, lookup, get_lightcurve, and
confirm recipes. Additional declarations are:

| Provider | Additional owned operations |
| --- | --- |
| ALeRCE ZTF and LSST | semantic_search, get_forced_photometry, get_classification, get_cutout, get_data_product |
| ANTARES ZTF and LSST | get_crossmatch |
| Fink ZTF and LSST | get_classification, get_crossmatch, get_cutout, get_data_product; LSST also get_forced_photometry |
| Lasair ZTF and LSST | get_classification, get_crossmatch |

Ownership does not guarantee support for every selector, band, time constraint,
response mode, or product kind. Product normalization deferrals, disabled LSST
AVRO, unowned search/SQL paths, and untranslated request variants keep their
existing boundaries. Scientific vocabulary and feature IDs are unchanged.

## Package and acceptance checks

`PYTHONPATH=. python scripts/check_release_package.py` builds a wheel with no
dependency installation, compares packaged runtime resources with the checkout,
and installs the wheel into a temporary target. From that installed copy it loads
all eight recipe providers, validates and plans cone discovery for each pair, and
checks the existing ALeRCE ZTF latest example. It performs no provider requests
and does not execute physical encoders or normalized-result assertions.

The DSL CI workflow runs this package check after its offline regression suites.
Live behavior still belongs to the acceptance scenarios on the user's machine;
see `scripts/smoke/README.md` and `scripts/live_dsl_facade_acceptance.py`.
