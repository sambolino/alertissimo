# Alertissimo architecture and development contract

This is the current ownership guide, read with `AGENTS.md`. Historical plans
describe their own checkpoints; current user instructions take precedence.

## Product and deployment

Alertissimo orchestrates heterogeneous astronomical providers into attributable,
object-centric semantic Portfolios. The current deployment target is **deploy
yourself**, with a UI and deterministic DSL. Future NLP may use the project's LLM
server and must emit the same validated DSL/IR, rather than directly call brokers.

Maximize scientifically meaningful broker diversity; do not manufacture candidate
classifiers or interchangeable products to fill a parity table. Shared temporal
operators/global latest still require identical scientific meanings across brokers.
Consult before adding any architecture layer.

Do not create a hosted session/database/service project. Explicit continuation
is already owned by the caller. The implicit single-client compatibility context
and its lock remain known constraints, outside the present cleanup scope.

## Canonical execution

UI/Python clients use `alertissimo.api`. Parsing and validation lower DSL into
`orchestration.ir`. Capability resolution and planning select admitted physical
realizations; binding resolves declared inputs. Staged execution obtains runtime
IDs and calls registry transports. Normalization and local semantics produce
immutable occurrence-aligned Portfolio views. Canonical serialization feeds UI
presentation. `WorkflowIR` owns scientific intent; `ResultViewSpec` owns display
intent. Neither stores UI session state, raw responses or provider-native SQL.

| Owner | Responsibility |
|---|---|
| `data_layer/semantic_model` | Ontology, semantic paths and semantic validation |
| `data_layer/providers/<broker>/<survey>` | Physical endpoints, field mappings and audited realization contracts |
| `data_layer/runtime` | Declaration interpretation, capability index and normalization/serialization support |
| `data_layer/execution` | Request validation, credentials, transport, pagination and physical provenance |
| `data_layer/transforms` | Declared pure value/request encodings |
| `orchestration/ir` | Canonical scientific operations and predicates |
| Orchestration validation/planner/binding | Eligibility, realizations, dependencies and physical input resolution |
| Orchestration pipeline/runtime/incremental/local semantics | Staging, lifecycle, reuse, material lineage and continuation |
| `data_layer/presentation` | Shared scientific extraction from normalized records |
| `ui_portfolios`, `app_plot`, `app_search`, `ui/` | Transient layout, controls, charts and evidence inspection |
| `api.py` | Public composition of these owners |

Root UI modules remain supported; moving files merely for directory appearance
is unnecessary. `app.py` launches `app_search.main`. UI controls may generate DSL
but may not invent their own executor or provider compatibility matrix.

### Declarations are complementary

`endpoints.yaml` describes physical calls; `mappings.yaml` gives returned fields
meaning and transformations; per-provider `capabilities.yaml` declares which
requests finite recipes satisfy, with required material and completeness claims.
`CapabilityGraph` is their derived index, not another scientific authority.
Recipe failure must not fall back to unrelated legacy endpoint evidence.

`with` requirements use Portfolio record nouns and admitted abstract families.
Ontology components and enum values do not become standalone request nouns. The
`measurement` record, explicit `lightcurve` series product, `data_product` artifact
and transient display projection remain distinct. Existing `GetLightcurveStep`
retrieval is not the unimplemented local `LightcurveStep` construction.

The recipe interpreter currently inspects IR field/operator contracts through
lazy imports in `data_layer/runtime/recipes.py`. This is an explicit, bounded
schema bridge, not another workflow implementation. The dependency graph is not
strictly acyclic. Relocating that compiler requires preserving one implementation
and graph behavior; do not duplicate IR schemas or add a coordinator to hide it.

## Scientific invariants

- Preserve semantic IDs, upstream assertions and original evidence. Keep ontology
  levels as declared by the ontology, including the survey container's L7. The
  old L0-L3 directory sketch is historical rather than the package map.
- Candidate identity is survey plus object ID. Catalogue context does not become
  candidate classification just because it contains a class label.
- Required evidence precedes whole initial-condition evaluation; admitted global
  `latest` follows initial selection. A later `filter` does not refill a population.
- Candidate filters select objects; measurement display controls select plotted
  values. Neither deletes evidence from a surviving object.
- Compare label/metric on the same assertion. Missing evidence is unknown, not a
  positive NOT result or a quorum vote. Confirm counts brokers, not proven
  independent methods.
- Stage selected IDs for downstream requests and finalize immutable material views
  afterward. Execution reuse does not erase scientific Step occurrences.
- Keep exact time bounds and resolved clocks. Pagination caps fail explicitly;
  there is no DSL 24-hour cap or permission to silently truncate.
- Probability, raw score, rank and observation/production/retrieval times are
  distinct. Scaling a score does not calibrate its scientific meaning.

## Shared photometry

`data_layer/presentation/portfolio_lightcurve.py` is the single row extractor for
typed and serialized Portfolios. The upload viewers and investigation adapter
consume it. It expands supported bands/quantities and distinguishes ordinary,
forced and upper-limit evidence, preserving unknown errors and negative fluxes.
An exposure's limiting depth alongside a measured value is retained as record
metadata, not plotted as a fabricated additional non-detection.
Adapters may attach record-local provenance and formatting, not re-parse field
names. Do not mix flux with magnitude on an axis, treat limits as measured
brightest/latest magnitudes, discard valid zero coordinates, or manufacture
records. Keep original evidence accessible through the inspector.

## Retired code and compatibility

The old executable `core.schema`/`core.orchestrator`, SMBBH pipeline, broker adapter
implementations and global capability-string loader are retired. They maintained
a competing IR/API route disconnected from the public facade. Source is retained
in Git history. Clients of those prototype classes must use `alertissimo.api`
or the canonical data-layer interfaces.

Old import paths under `core/portfolio`, `core/brokers/execution` and the remaining
registry shims still alias the exact canonical objects. They are compatibility
imports, not engines. Do not reconstruct the removed broker factory behind them.

## Functional priorities

[Next functional work](docs/next_functional_work.md) owns the implementation IDs,
current/target states and completion criteria. The reviewed headline selection and
finite vocabulary policy is recorded in [classification headline policy](docs/classification_headline_policy.md).
It is opt-in in the first policy PR; execution, normalized confirmation and UI
integration remain subsequent work. Fresh ALeRCE/ZTF classification retrieval
now supplies broker-selected LC and stamp summaries alongside all probability
versions through its existing declarative recipe.

- Coarse normalization translates the selected native headline through an explicit
  vocabulary. `best` does not choose a scientifically strongest cross-broker result.
  Prefer the broker-designated headline; use the reviewed Alertissimo method
  default where designated. Keep native outputs, scope, conflicts and alternatives.
  No cross-method score comparison or additional probability threshold is used.
  Confirm retains broker-local evidence and counts each broker at most once.
- Catalogue coverage is a major workstream. Extend existing debt/audit machinery,
  mapping every scientifically established field possible and correcting existing
  meanings. Preserve catalogue-source scope and producer/channel attribution.
- Complete semantic discovery and uniform within/first/last/latest behaviour.
  Native and complete local realizations may differ; population and meaning may
  not. A missing recipe is an implementation gap, not provider impossibility.
- [Collection predicates](docs/dsl_collections.md) use ontology path parameters,
  relative element paths, filtered aggregates and parenthesized quantifier bodies.
  Extend existing semantic-model/expression/IR owners rather than add an engine.
- Preserve measurement/product/display boundaries. Non-detections are measurements;
  missing flux alone does not establish one, and limiting depth alongside a value
  is not another observation.
- Cutouts follow the higher-priority scientific work. Optional `as p` bindings and
  the FP surface/acquisition policy remain deferred for reevaluation. Do not
  broaden the Portfolio noun rule or change automatic FP supplementation now.

The [field coverage contract](docs/provider_field_coverage.md) owns the audit
checklist and dated targeted-catalogue snapshot. The existing
[discovery guide](docs/discovery_integration.md) remains the implementation support
baseline. Neither a mapping nor an admitted plan is live acceptance.

## Verification

Choose tests by changed owners. Presentation changes need both UI paths, scientific
edge cases and frozen-fixture checks; provider changes need declaration validation
and native/local population equivalence; orchestration changes need predicate,
lineage, reuse and continuation regressions. Run package checks when packaged
modules/resources change. Final CI must correspond to the implementation merged.

AppTest does not execute editor JavaScript in a browser. Planning is not provider
acceptance. Keep empty, unavailable, policy failure and nonempty PASS separate,
with the tested SHA and actual scope. The user performs pushes/PRs/merges; provide
copyable commands and reviewable bundles rather than mutating GitHub through tools.
