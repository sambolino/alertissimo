# Alertissimo architecture and development contract

This is the current ownership guide, read with `AGENTS.md`. Historical plans
describe their own checkpoints; current user instructions take precedence.

## Product and deployment

Alertissimo orchestrates heterogeneous astronomical providers into attributable,
object-centric semantic Portfolios. The current deployment target is **deploy
yourself**, with a UI and deterministic DSL. Future NLP may use the project's LLM
server and must emit the same validated DSL/IR, rather than directly call brokers.

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

The recipe interpreter currently inspects IR field/operator contracts through
lazy imports in `data_layer/runtime/recipes.py`. This is an explicit, bounded
schema bridge, not another workflow implementation. The dependency graph is not
strictly acyclic. Relocating that compiler requires preserving one implementation
and graph behavior; do not duplicate IR schemas or add a coordinator to hide it.

## Scientific invariants

- Preserve semantic IDs, upstream assertions and original evidence. Keep ontology
  levels distinct: the current model declares L0-L6; the old L0-L3 directory sketch
  is historical rather than the package map.
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

**Coarse classification normalization, universal `best`, and selected DSL
improvements are user-required release priorities.** They are not implemented
by this cleanup and must not be dismissed as optional beta extras.

Before implementing their scientific rule contract:

1. Identify eligible producers, outputs and versions. A listed, low-ranked class
   assessment is not automatically support for that class.
2. Declare coarse label support and method-specific acceptance rules. A generic
   SN label supplies no SNII subtype; contextual associations retain their scope.
3. Define universal `best` as a derived assertion under a named/versioned rule,
   retaining inputs, alternatives and provenance. Never maximize incomparable raw
   scores or overwrite upstream preferred outputs.
4. Keep attribution so confirmation can evaluate normalized evidence in each
   broker's own material. A global winner must not manufacture several votes.
5. Add elegant collection-level reasoning using a small reusable expression model:
   filtered `count(...)`, and quantified per-band conditions. The user's examples
   ask for at least five high-real/bogus measurements, a total valid-point count,
   and at least five valid points in every requested Rubin band. Use the current
   `measurement` noun rather than the retired `detection` name. Aggregation scope,
   variable binding and missing-data semantics must be explicit; these examples
   are requirements, not currently implemented syntax. Avoid special-purpose
   keywords for individual scientific cuts. See `docs/next_functional_work.md`.

Full broker parity means all operations on all broker/survey combinations. It is
not an assumed requirement. Existing admission and deferrals are recorded in
`docs/discovery_integration.md`, not in a hand-maintained UI matrix.

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
