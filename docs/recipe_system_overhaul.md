# Recipe system overhaul

Baseline: `main` at `18713d4a6237984fc60ff62979364fa3e25ddaf3`.

The planner will select provider-local declarations of how existing IR operations
become physical calls. `CapabilityGraph` will compile those declarations alongside
endpoint contracts and response mappings. The migration keeps WorkflowIR,
Portfolio identity, staged execution, request encoding, and normalization intact.

## Sources of truth

| Source | Owns |
| --- | --- |
| Existing IR models | Operation discriminators, workflow inputs, predicates, selections, and lifecycle semantics |
| Existing ontology | Scientific records, fields, and qualifiers |
| Provider `endpoints.yaml` | Physical API signature, transport, defaults, types, collection limits, and value encoding |
| Provider `mappings.yaml` | Payload locations, raw-field meanings, normalization transforms, and partition identity |
| Provider `capabilities.yaml` | Recipes and request-side semantic translations |
| `CapabilityGraph` | Compiled evidence and recipe index; no independently authored vocabulary |

Use the exact `Step.op` values. Do not add capability names such as
`compact_cone_search`, alternate verbs, a canonical parameter registry, or
recipe-level copies of `semantic_type`. Match requested semantic material against
mapping-derived evidence before execution, retaining producer/channel qualifiers.

There is already an unrelated central
`alertissimo/data_layer/runtime/capabilities.yaml`, loaded by legacy broker code.
The new files live under `alertissimo/data_layer/providers/<broker>/<origin>/`.
Audit consumers before changing the legacy file; sharing a filename does not make
the two registries interchangeable.

## Minimal recipe contract

Recipes are keyed by existing IR operations. A list permits alternatives without
inventing global capability IDs. Physical endpoint names remain provider-local.
This is the proposed v1 shape; branch 02 must validate it against actual bindings
before activating it:

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
              from:
                call: 0
                path: summary.identity.object_id
            selected:
              value: objects.objectId,objects.ramean,objects.decmean,objects.ncand,objects.jdmin,objects.jdmax
            tables: {value: objects}
            limit: {value: 100}
            offset: {value: 0}
```

`from` and `value` are mutually exclusive. Sources are parsed references, not
Python, string interpolation, or arbitrary expressions. Validate direct paths
against the concrete IR model selected by `op`; validate dependency paths against
the owning call's mappings. Zero-based call references must point backwards.
Ordered calls therefore form an acyclic dependency graph without a new graph DSL.

For v1, cross-call values are restricted to normalized candidate identity, which
the current `PlanCandidateInputRef` and staged pipeline already support. Reject
other output references until an actual use case requires expanding that runtime
contract. Do not advertise a generic field-reference runtime that does not exist.

`step.target.ids` is the authored target source. Its compiled representation must
preserve existing explicit-target, earlier-Step candidate, and execution-reuse
rules. Runtime candidate values never get copied into WorkflowIR.

Encoding remains physical: CSV, scalar fan-out, SQL membership, SkyCoord, Angle,
and unit conversions use existing transforms. Recipe sources feed encoder inputs;
they do not contain invented adapter names. The schema must cover ANTARES's
multi-input center encoder as well as single-input parameters. Keep legacy
`bind`/`binding.roles` during migration; move semantic source assignments only
after the compiled binder interface is established. Encoder operand labels are
not a second public intent vocabulary.

Call constants belong in that call's `params`. Parameter defaults remain in the
endpoint contract. Do not turn an endpoint default into proof that a particular
projection or response mode satisfies a recipe.

## Correctness rules

- Endpoint-specific field evidence must not inherit another endpoint's fields.
  A mapping describes possible material, not guaranteed non-null values or the
  result of every projection. Preserve payload and qualified path evidence.
- Required and optional calls contribute different evidence. An optional summary
  may improve display richness; it cannot be the sole proof for a mandatory
  predicate field, selection key, or later required binding. Promote a needed
  call to required only when the requested semantics justify that change.
- Validate identity and partition compatibility using current mappings and
  consolidation. Do not blindly union outputs from unrelated objects, surveys,
  producers, or channels, or invent a second merge policy.
- Unsupported predicate pushdown becomes residual only when normalized material
  is available for evaluation. Missing fields require retrieval or an explicit
  unsupported/deferred result; residual evaluation cannot create them.
- A fixed threshold parameter consumes only predicates with its verified
  operator. Expression endpoints may encode the IR operator only through a
  declared, validated translation. Never infer a comparison from a parameter's
  name or assume `>=`. Keep current operator semantics during relocation;
  expanding SQL predicate support is a separate implementation decision.
- Partial pushdown across conjunctions must preserve a candidate superset.
  Preserve existing treatment of OR, NOT, conflicting assignments, and qualifiers.
- Push `latest` down only with a proof about ordering, filtering, pagination, and
  the entire candidate population. A dependency call limited within each batch
  is not a global latest-N result. Keep semantic selection after normalization.
- Empty candidate dependencies remain vacuous calls, not failures. Preserve batch
  limits, provenance, sparse plan/result alignment, continuation, and call reuse.
- Confirmation quorum, local Filter/Match/Derive, and workflow accumulation remain
  orchestration semantics. Provider declarations supply confirmation evidence;
  they do not enumerate broker combinations or implement quorum.
- No expression conditions, cost scores, silent YAML-order priorities, or inferred
  SQL translations in v1. Equally feasible alternatives remain ambiguous.

## Incremental branches

Each branch starts from updated `main` after its predecessor is merged. Do not
pre-create empty future branches or maintain a second integration branch. Include
the exact local verification commands in every handoff. Add small regression
cases for meaningful contract changes; run them on the user's machine.

| Branch | Deliverable and boundary |
| --- | --- |
| `refactor/recipes-01-output-index` | This branch: endpoint-specific mapped-field query, one regression case, this plan, and local runbook. No planning behavior change. |
| `refactor/recipes-02-registry` | Strict recipe parser/compiler and graph index. Validate existing op/path/endpoint/parameter references, source forms, backwards dependencies, constants, and encoder compatibility. Cover scalar, collection, and multi-input encoders. Load additively; do not activate recipes yet. Add new-file CI path coverage and verify package inclusion rules. |
| `refactor/recipes-03-atomic-cone` | Activate single-call cone recipes across supported broker/survey paths. Compile ordinary IR sources into binder input without changing physical encoders. Reuse the existing staged runtime. Retain current unsupported combinations and ambiguity behavior. |
| `refactor/recipes-04-lasair-cone` | Replace `_lasair_ztf_cone_summary_supplement` and its six-column constants with the two-call recipe. Compile the dependency to existing `PlanCandidateInputRef`. Preserve optional failure, 100-ID batching, identity, and one semantic Step. No generalized output-reference framework. |
| `refactor/recipes-05-lightcurves` | Migrate `get_lightcurve` and `get_forced_photometry`, replacing `_forced_photometry_supplement`. Preserve its restrictions for bands/time context, forced-point reuse, and optionality. Check which calls actually contribute canonical lightcurve material instead of treating record-family union as sufficient. |
| `refactor/recipes-06-retrieval` | Migrate lookup and remaining currently supported Get operations, including classifier/catalog constraints and scalar-versus-collection eligibility. Preserve unsupported/deferred cases. Split this branch by operation if the diff becomes large. |
| `refactor/recipes-07-predicates` | Move existing request mappings into provider capabilities and compile them to the existing `RequestConstraintCapability`. Keep explicit operators, qualifier handling, and `PredicateRealization`. Make bindings call-scoped so a later enrichment predicate cannot incorrectly prune the discovery population. Preserve current behavior first; do not add generic SQL predicate compilation here. |
| `refactor/recipes-08-selection` | Declare selection translations and safety checks. Start with one verified ordering/limit contract, then migrate equivalent cases. Global normalization/selection remains authoritative. Split by provider if proving contracts requires separate changes. |
| `refactor/recipes-09-cutover` | Complete currently supported semantic-search/SQL paths and confirmation evidence selection. Make planning and capability validation use one candidate-resolution implementation, preserving diagnostics and public validation behavior. Use validated registry evidence for reuse. Local orchestration still owns quorum and candidate reduction. |
| `refactor/recipes-10-cleanup` | Remove migrated tags, binding-source declarations, request-mapping files, and compatibility routing after a consumer audit. Update architectural documentation and CI triggers. Consolidate overlapping loading only if it reduces duplication without changing executor/normalizer responsibilities; otherwise keep that as a later branch. |

The retrieval stage is split by operation, beginning with
`refactor/recipes-06a-lookup` and then classification retrieval.
The cutover stage also proceeds in small branches. `refactor/recipes-09a-search`
migrates ALeRCE ZTF/LSST semantic discovery and shares its candidate resolver with
cone recipes. SQL translation, confirmation evidence, and reuse audits remain
separate follow-ups before cleanup.
`refactor/recipes-09b-confirmation` declares target-bound confirmation evidence
across the eight existing broker/survey contracts. DSL confirmation validation and
planning consume the same recipe resolver; quorum remains an orchestration rule.
`refactor/recipes-09c-sql` checks the whole-query binding required by the existing
SQL IR. Lasair split-query contracts defer consistently before planning. Direct
whole-query recipes use the shared discovery resolver and physical query role.
`refactor/recipes-09d-reuse` requires candidate-search reuse to match a selected
required recipe call and its compiled outputs. Optional supplements cannot satisfy
a later mandatory retrieval. Remaining semantic-provider eligibility is audited
separately before cleanup.

During migration, fall back to the legacy planner only for an operation/source
with no migrated recipe. A malformed declaration, unsatisfied recipe, or ambiguous
recipe must fail visibly; do not hide it by taking the old path. Once an operation
is migrated, recipe resolution owns it even for unsupported input variants.

Branch 02 should group request-side translations with their owning call where
possible. Avoid three independent authored copies of parameter bindings. Fixed
threshold and selection rules must remain distinguishable from ordinary value
assignment because they consume semantic intent and carry equivalence claims.
Freeze their detailed YAML only when those branches inspect the actual contracts.

## Implementation locations

Extend `alertissimo/data_layer/runtime/capability_graph.py` and place strict recipe
loading next to it. Reuse its immutable runtime style; validate YAML structure and
cross-references without creating a parallel scientific type system. Reuse the
existing IR and ontology for legal concepts. Keep graph construction independent
of network execution.

Planner activation touches `orchestration/planner/planner.py`,
`orchestration/validation.py`, and the compiled binder interface. Existing
`orchestration/runtime/models.py` and `orchestration/pipeline.py` already provide
intra-Step candidate dependencies and optional execution. Extend these only for a
proven gap. `data_layer/execution/executor.py` still executes one bound invocation;
normalization still interprets physical responses through mappings.

## Local verification budget

No test execution is performed in the editing environment for this series.
The branch handoff supplies focused commands; the user runs them and returns any
failures. Do not install the full application stack solely to validate a small
registry or graph change. Branch 01 commands are in the companion runbook.

Useful existing regression targets for later handoffs:

- Graph/loading: `tests/test_capability_graph.py`, plus the new recipe-contract
  module introduced in branch 02.
- Cone/binding: `tests/test_orchestration_planner.py`,
  `tests/test_orchestration_spatial_binding.py`,
  `tests/test_orchestration_antares_cone_binding.py`.
- Composite cone: `tests/test_lasair_ztf_compact_cone_summary.py`,
  `tests/test_orchestration_supplementary_plans.py`,
  `tests/test_orchestration_endpoint_pagination.py`.
- Lightcurve/reuse: `tests/test_orchestration_lightcurve_forced_reuse.py`,
  `tests/test_orchestration_execution_coalescing.py`.
- Predicate/selection: `tests/test_dsl_predicate_realization.py`,
  `tests/test_orchestration_residual_pruning.py`, and focused selection cases.
- Cutover: existing capability-validation, confirmation, continuation, and smoke
  coverage, followed by one broader DSL/orchestration pass before cleanup.

Live acceptance runs belong on the user's machine at the relevant migration
milestones, not after every documentation or graph helper change. Existing
scenario names include `dsl-lasair-compact-summary`, `explicit-multi-target`,
`fink-lsst-consolidation`, `dsl-classification-reuse`,
`dsl-confirm-predicate-quorum`, and `dsl-incremental-continuation`.

No test results are claimed for branch 01. The new field query is an additive
inspection API; subsequent recipe branches will use it.
