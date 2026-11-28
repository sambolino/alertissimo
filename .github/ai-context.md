# Current developer context

Read [AGENTS.md](../AGENTS.md) and [ARCHITECTURE.md](../ARCHITECTURE.md) for operating
rules and architecture pillars, then the relevant repository procedure.

[Next functional work](../docs/next_functional_work.md) owns stable implementation
IDs 1–11 and their current/target states. Coarse classification, universal best,
catalogue diversity, semantic discovery and uniform temporal/latest selection are
required priorities. Cutouts are the last required feature expansion.

- [Collection contract](../docs/dsl_collections.md): counts/extrema use ranges;
  quantifiers use Kleene logic and exact NOT duality. Membership is branch-local.
  Admitted filters use guaranteed preceding material and preserve non-refilling
  latest, occurrence lineage and immutable continuation. Competing products retain
  visible StepRun warnings. Initial collections/latest and missing material remain
  item 4a; collection confirmation is outside the admitted scope.
- [Item 7](../docs/next_functional_work.md#7-measurements-non-detections-and-lightcurve-boundaries)
  is complete for its agreed scope: `with measurement` has all eight acquisition
  recipes; native status flags keep ordinary and forced populations distinct;
  ontology-valid product.component requirements strengthen only that Get's own
  producing calls. References strengthen matching unexecuted Gets, never add one
  or rewrite a completed prefix. Required failure is visible; explicit empty
  receipts do not fabricate records. Plain requests retain optional-call policy.
- Detection-scoped completeness uses existing ZTF material proofs plus raw-row,
  identity and normalized-point accounting. Delivery is separate: g/r for ALeRCE
  and ANTARES, g/r/i for Lasair. Unknown/dropped rows withhold closure; proof
  inspection does not invoke lazy getters. Mixed nonempty totals, extrema,
  measurement collections and LSST remain open. Lasair's two original captures
  retain 688 forced epochs, native flux/error and separate calibration zero points.
- New WorkflowIR uses version 3. Measurement retrieval and nonempty required
  components need 3; collection syntax needs 2. Older workflows retain their
  version/wire shape and are never upgraded implicitly. Scalar/taxon contracts
  and the retained classification-policy interpretation stay unchanged.
- Use the documented scientific idioms and their limits. Exact last-limit/first-
  detection ordering and arbitrary flux/error significance multipliers still need
  separate DSL review (items 6/10); local `LightcurveStep` construction is deferred.
  Optional `as p` remains item 10; new photometry computation remains item 11.
  LSST precovery availability depends on retrieval time; do not infer survey or
  collection completeness from the ordinary detection flag.
- The maintainer runs tests and all implementation Git/GitHub commands locally.
  Deliver generated `.patch` files only through `artifact-delivery`; leave
  implementation branches and PRs untouched. Include fetch/git-show, apply,
  appropriate local checks, commit/push/PR/check/squash/update commands. Do not use
  sandbox downloads or inline Base64 unless requested. Markdown-only closeout
  does not call for a repeated backend suite.
- [Field coverage](../docs/provider_field_coverage.md): extend existing ledgers and
  audit tooling; preserve catalogue scope, units and ownership.
- [Discovery baseline](../docs/discovery_integration.md): route-specific admitted
  behaviour, not a complete beta target or fresh all-provider live report.

Keep Portfolio nouns as the basis of `with`. Components are requested beneath
their product noun; `with forced_photometry` is not an admitted standalone noun.
Classification headlines follow the reviewed
[ELAsTiCC policy](../docs/classification_headline_policy.md); additional thresholds
or precedence changes require explicit scientific review.

Deployment is deploy-yourself with deterministic DSL and UI; future NLP emits the
same DSL/IR. Consult before a new architecture layer. Do not add hosted session,
database or service infrastructure. The user controls GitHub mutations.

The obsolete execution stack is retired and both photometry paths share scientific
extraction. Superseded development notes remain in Git history. Fresh and reused
enrichment must preserve selected candidate membership during staging,
normalization and finalization, while retaining complete execution evidence.
Continuation keeps the finalized prefix and its stored policy interpretation.

CI checks the whole PR diff with `scripts/ci_change_scope.py`. Markdown and
verified YAML comment/formatting changes skip backend suites. The scope helper,
its tests and the three existing workflows use focused CI regressions; other
changes keep full applicable suites. Manual workflow dispatch forces full runs.
Keep required `validate` check names and do not replace uncertainty with a skip.
