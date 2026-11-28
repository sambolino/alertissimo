# Alertissimo architecture and development contract

This is the current ownership guide, read with `AGENTS.md`. Superseded milestone
notes are available in Git history; current user instructions take precedence.

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

`with measurement` uses `GetMeasurementStep` and provider-local `get_measurement`
recipes for the broker's existing per-epoch observations, including supplied limits.
It shares the existing retrieval, binding and material-lineage owners. Optional
forced calls follow the lightcurve policy. No recipe means unsupported acquisition;
incidental measurement predicates retain their existing scheduling. Measurement
record counts remain open; the audited detection-count rules below apply only to
eligible lightcurve populations. ALeRCE/LSST retains forced-only measurement epochs
and own-epoch forced values on detections without merging them with the forced
series product. LSST precovery arrives through alerts after discovery and depends
on retrieval time; missing magnitude/flux is never an ordinary limit flag.

An ontology-valid `with <product>.<component>` records qualified semantic references
in the Get's `required_components`. The existing resolver promotes every producing
call within that product's own recipe, without changing declarations or importing
another operation's calls. References strengthen matching unexecuted Gets; completed
continuation prefixes stay immutable. Required empty successes keep the object;
existing receipts can prove an empty requested array transiently, without adding
Portfolio fields or fabricated records. Missing/malformed arrays and normalization
loss are not empty evidence. Scalar values keep their existing existence semantics;
container existence asks for supplied content. Sibling arrays are distinct, while
multiple records carrying the requested array remain ambiguous. Unrestricted
nonempty histories remain open; only the audited detection subsets can close count
bounds. Empty component metadata is omitted from serialization;
nonempty metadata requires version 3, preserving older workflow wire formats.

An abstract-family request expands deterministically into supported concrete Gets
using the supplied capability graph and candidate origins. Identical explicit or
continued requests are deduplicated. Deferred members are not activated, an empty
expansion fails, and admitted required-call failures are not silently skipped.
Family-level producer/method restrictions and predicates are rejected rather than
distributed across heterogeneous children. `$is` expresses transitive family
membership without copying fields; abstract containers cannot be instantiated.

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
- Fresh and reused targetless enrichment extend only the source candidate
  population; complete physical responses remain available as execution evidence.
- Keep exact time bounds and resolved clocks. Pagination caps fail explicitly;
  there is no DSL 24-hour cap or permission to silently truncate.
- Probability, raw score, rank and observation/production/retrieval times are
  distinct. Scaling a score does not calibrate its scientific meaning.

### Predicate and confirmation scope

Each exact `(record noun, producer, channel)` selector has one assertion witness
across the whole Boolean expression, including mixed summary/classification
conditions. Different explicit selectors can have different witnesses. If native
pushdown consumes one condition but leaves another on the same selector local,
retain the original predicate as residual: server object selection does not
identify its assertion witness. Required projected material must prove that
residual can be evaluated before execution.

For ordinary scalar comparisons, missing/null/nonfinite values, incompatible types
and nonscalar operands are unknown. Numeric strings are not coerced and booleans
are not scores. Only established True selects or votes. NOT preserves unknown.
Explicit NOT EXISTS checks all matching records in the current material view; a partial record cannot
prove absence if another supplies the field. This is not evidence of absence at
an unqueried provider or proof of retrieval completeness.

One authored confirmation condition survives intervening material requests,
initial selectors and view ordering. Filter, Match or an earlier Confirm ends
attachment; a new API fragment does not inherit a prior call's proposition.
Different canonical conditions in one confirmation stage are ambiguous and rejected;
repeated identical conditions are not. A bare Confirm asks about existence.
Each voter must prove the whole proposition from its own occurrence-local evidence.

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
It is integrated as stored `classification@headline:<broker>` records. Shared
presentation reads the stored result; it never derives scientific fields. Normalized
Confirm composes its own classification recipe evidence per broker before voting.
Continuation preserves finalized prior material and its pinned policy interpretation. Fresh ALeRCE/ZTF classification retrieval
now supplies broker-selected LC and stamp summaries alongside all probability
versions through its existing declarative recipe.

- Headline normalization maps selected native labels to ELAsTiCC code sets plus a
  reviewed local extension. Explicit ancestry gives support/opposition/unknown;
  aliases resolve once into strict frozen IR tuples that never reach pushdown. `best` does not choose a scientifically strongest cross-broker result.
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
  The ordered ontology reader retains array items and scoped parameter domains;
  syntax/IR adds scoped aggregates and quantifiers. Local evaluation extends the
  existing normalization predicate owner with ranges and Kleene quantifiers.
  The existing capability validator/planner admit filters from guaranteed preceding
  required-call outputs and projections, preserving origin and classifier scope.
  Static product ambiguity uses occurrence-local/inherited material. Initial
  collections plus latest and unproven material report item 4a; collection confirm
  is rejected. Scalar continuation retains its version; collections require 2.
  Ambiguity uses existing StepRun warnings, surviving
  rejected candidates, serialization and immutable continuation; acquisition
  warnings still block continuation. Physical audit projection follows the
  material decision rather than re-evaluating collection fragments. Synthetic
  transient evidence exercises complete bounds. Existing ZTF material detection
  proofs plus raw-row/normalized-point accounting can close detection-only counts
  for ALeRCE, Lasair and ANTARES. Batch parents and global source indices stay
  identity-bound; unknown/lost rows withhold closure. Delivery is separate immutable
  RecipeCall metadata: g/r for ALeRCE/ANTARES, g/r/i for Lasair. Empty histories can
  supply scoped zero-count receipts without fabricated records. Proof inspection
  never invokes lazy getters. Mixed nonempty totals, extrema, measurement and LSST
  completeness remain open. Required-component receipts independently prove explicit
  empty arrays; no persisted result fields are added.
  No Portfolio/result schema or runtime layer is added. WorkflowIR carries
  `dsl_version`: new construction uses 3; unversioned serialized IR loads as 1,
  and newer versions are refused. Existing version-1/2 workflows retain their
  versions; `get_measurement` requires 3 and cannot implicitly upgrade continuation.
  Route delivery and collection completeness are
  separate evidence; observed bands establish neither the full domain nor completeness.
- Preserve measurement/product/display boundaries. Non-detections are measurements;
  missing flux alone does not establish one, and limiting depth alongside a value
  is not another observation.
- Cutouts follow the higher-priority scientific work. Optional `as p` bindings and
  on-demand FP computation remain deferred. The component rule retains Portfolio
  nouns and preserves automatic supplementation when no component is required.

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
