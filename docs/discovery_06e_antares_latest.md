# ANTARES global latest from complete detection history

Branch `feat/discovery-06e-antares-latest`, based on integration `adfccfb` /
PR #320. Target `integration/discovery-completion`; squash after local checks.

## Behavior

```text
objects from ztf via antares
where summary.position.ra >= 50.847 and summary.position.ra <= 50.849 and summary.position.dec >= 37.467 and summary.position.dec <= 37.469
within 7d
latest 5
```

The numeric coordinate condition remains required. `latest N` works without a
window, or after default, first, or last within. Exhaust native discovery, recheck
the coordinate predicate and ZTF identity locally, retrieve required histories,
apply temporal membership, consolidate objects, and then rank globally. Rank by
the greatest valid detection MJD in the complete reported history, including
detections outside the membership interval. Equal dates use `(origin, object_id)`
as the deterministic tie breaker. All measurements of survivors are retained.

An upper limit cannot establish detection recency. Empty discovery is a valid
empty result. A selected population containing an object with no detections or
unknown/malformed history cannot establish a correct latest sample and fails
explicitly, including when that object appears older than the provisional cut.
Default within can still exclude a complete empty/limit-only history before
ranking. No summary date is synthesized from alert timestamps or detections.

The ordinary unwindowed search still needs one native search call. Latest adds
required `get_by_ztf_object_id` per discovered object. Temporal searches already
have those histories; ranking does not issue another history request. These are
native entry-point counts: Locus lazy relationships can make additional HTTP
requests. This branch does not migrate the pinned ANTARES client or promise a
server-side top-N optimization.

## Existing proof extension

The existing recipe `latest_selection` accepts an explicit history branch:

```yaml
latest_selection:
  call: 1
  complete: true
  history:
    payload: locus_alerts
    time_scale: utc
    detection_identity: detection.identity.source_id
```

Compilation reuses the existing complete material time proof with last/max
reduction. It requires uncapped native iterator discovery, identity-scoped
predicates, required singular history consuming discovery object IDs, no other
history parameters, and mapped time, ordinary photometry, source identity and
response object identity. The compiled ranking plan carries the same temporal
proof and mapped partition fields through serialization.

The common detection reader now supplies both temporal membership and ranking.
It checks the originating execution and payload branch, finite ordinary
photometry/time and ZTF source identity. The shared raw temporal guard also checks
ranking histories for missing collections and per-request object coverage.
Staged execution and offline normalization both pass the serialized plan into
the existing latest reducer. Legacy summary-based latest proofs keep their
existing exact raw coverage checks and predicate restrictions.

Latest remains a barrier to broad raw-execution reuse by a later lightcurve Get.
Continuation replays every original physical history, preserves the discovery
clock and selection, and binds new retrievals only to current survivors. It does
not re-fetch discarded candidates or mutate historical Step views.

This extends existing recipes, validation, plan models and normalization. It adds
no architecture layer, IR operation, DSL keyword, ontology leaf or mapping.

## Locus identity and native cone review

Read-only inspection reconfirmed the pinned
[ANTARES 1.14.0 search source](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/944197ad2bdae5b46641ddf5f76711e1e327e6f0/antares_client/search.py).
Search exhausts `_list_all_resources`; its native order is newest **alert**
observation time, which does not prove latest **detection**. Object lookup takes
the first matching locus, and the
[Locus alert contract](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/944197ad2bdae5b46641ddf5f76711e1e327e6f0/antares_client/models.py)
describes historical alerts associated with that locus. The complete-history audit
and selected-lightcurve limitation remain documented in [06c](discovery_06c_antares_within.md).

The unchanged cone capture has three different locus IDs sharing
`ZTF20aafqubg`. Therefore deduplicating object IDs alone cannot prove that a
first-match lookup supplies the appropriate complete history. Latest now requires
one discovery locus per ZTF ID and checks that the returned history has that same
locus identity. Repeated rows for the same locus are harmless; conflicting loci
or a different returned locus fail explicitly. Combining histories from multiple
ANTARES loci is not implemented by silently accepting the first one. These new
ranking guards do not expand the older within contracts.

The native cone function sends only `sky_distance`/`htm16`, with no ZTF identity
scope. Its temporal and latest forms remain explicitly deferred; this review does
not advertise them as supported. The activated coordinate search has the existing
server identity scope and local identity residual. A future cone activation needs
that positive survey scope before targeted history binding, plus the same locus
coverage protection. Ordinary existing cone behavior is unchanged.

Additional Rubin discovery and classification joins remain end-of-series
consultation items. Required material is the next planned branch.

## Local checks and checkpoint

No tests, project imports, builds, apps or live requests ran here. Static AST,
YAML, whitespace and Git bundle verification accompany this branch.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_antares_time.py \
  tests/test_antares_semantic_search.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_lasair_time.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_time_membership.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-discovery-06e-tests.log
```

New cases cover ranking with every admitted time mode, complete pre-ranking
history retrieval, out-of-window extrema, distant upper limits, deterministic
ties, duplicate discovery rows, overbroad response pruning, invalid histories
below the provisional cutoff, empty discovery, unrankable empty histories,
required-call failures, plan serialization, offline replay, survivor-only
continuation, capped/unscoped declarations, and conflicting locus histories.
Existing Lasair/ALeRCE selection regressions cover the shared normalization paths.

After local success and squash into integration, run the manual shared DSL
checkpoint against the **updated** branch:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh run list --workflow dsl.yml --branch integration/discovery-completion --limit 3
```

Use the newly dispatched run ID with `gh run watch RUN_ID --exit-status`. Do not
rerun an older SHA. No separate per-feature automatic CI is needed. Final full CI,
installed-package validation, and local provider acceptance still precede main.
