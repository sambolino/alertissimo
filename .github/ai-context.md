# Current developer context

Read [AGENTS.md](../AGENTS.md) and [ARCHITECTURE.md](../ARCHITECTURE.md) for operating
rules and architecture pillars, then the relevant repository procedure.

[Next functional work](../docs/next_functional_work.md) owns stable implementation
IDs 1–11 and their current/target states. Coarse classification, universal best,
catalogue diversity, semantic discovery and uniform temporal/latest selection are
required priorities. Cutouts are the last required feature expansion.

- [Collection contract](../docs/dsl_collections.md): ontology parameters, relative
  element paths and parenthesized bodies; examples remain unimplemented.
- [Field coverage](../docs/provider_field_coverage.md): extend existing ledgers and
  audit tooling; preserve catalogue scope, units and ownership.
- [Discovery baseline](../docs/discovery_integration.md): route-specific admitted
  behaviour, not a complete beta target or fresh all-provider live report.

Keep Portfolio nouns as the basis of `with`. Optional `as p` and the FP surface/
acquisition policy are deferred; neither new FP nouns nor automatic-policy changes
are approved. Classification headlines follow the reviewed
[ELAsTiCC policy](../docs/classification_headline_policy.md); additional thresholds
or precedence changes require explicit scientific review.

Deployment is deploy-yourself with deterministic DSL and UI; future NLP emits the
same DSL/IR. Consult before a new architecture layer. Do not add hosted session,
database or service infrastructure. The user controls GitHub mutations.

The obsolete execution stack is retired and both photometry paths share scientific
extraction. Earlier context is retained in
[history](../docs/history/developer_context_before_architecture_cleanup.md).

## Classification integration CI repair (PR #355)

Based on integration head `e9f085be587ecb66c6e80e5de3c22b398b6d717e`.
The failed DSL/semantic jobs reported 37 distinct cases (24 overlap).

- ALeRCE/ZTF classification recipes now require probabilities plus targeted LC
  and stamp summaries. Fixture clients must distinguish those calls from initial
  discovery, honor `oid`, and account for all three calls per candidate.
- ANTARES/ZTF candidate retrieval is admitted. Catalogue labels remain crossmatch
  evidence and do not become candidate classifications or headline taxon votes.
- The API finalizer preserves the continuation prefix and replaces the staged
  dataclass with its finalized normalized view. Test doubles must model both.
- Fresh enrichment, like reused enrichment, must extend only the source candidate
  population. Enforce this during staging, normalization and finalization; retain
  complete physical execution evidence. Regressions include empty populations,
  rejected IDs, survey collisions, unknown identity and immutable continuation.
- Both main-target CI suites now emit `--durations=25`. One representative local
  profile found repeated YAML policy parsing dominant, with 24 policy loads and
  one graph build. This is a sample, not a suite-wide timing attribution. No cache
  or test-scope changes are part of the repair.

Validation is offline; no new provider acceptance or scientific policy is claimed.
The user applies the repair to `integration/classification-headlines` and reruns
the existing PR checks. Do not merge #355 based on the old failed CI or on focused
local validation alone.
