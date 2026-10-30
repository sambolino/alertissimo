# ANTARES ZTF default within from complete alert history

Branch `feat/discovery-06c-antares-within`, based on integration `a6909e8` /
PR #318. Target `integration/discovery-completion`.

The 06b manual DSL checkpoint
[40984533355](https://github.com/sambolino/alertissimo/actions/runs/40984533355)
passed at that integration revision. This branch has only static verification
here; tests and provider requests remain local to Veljko.

## Activated request

```text
objects from ztf via antares
where summary.position.ra >= 50.847 and summary.position.ra <= 50.849 and summary.position.dec >= 37.467 and summary.position.dec <= 37.469
within 7d
with lightcurve via antares
```

Default `within` means at least one detection inside the closed interval. Relative
windows end at one fixed UTC reference instant for this discovery occurrence;
explicit intervals retain their bounds and offsets. Every returned measurement
of each surviving object is retained, including observations outside the window
and upper limits.

The existing coordinate query still defines the discovery population. This
recipe does not send a misleading newest-alert date condition to the index.
It exhausts the coordinate search, then requires `get_by_ztf_object_id` for every
discovered identity. This can cost more than a native indexed window: completeness
and actual detection membership are checked using the returned alert history.
A bare `within` without an eligible coordinate predicate does not become a full
catalogue scan. The original unwindowed recipe remains separate.

## Existing recipe and evidence paths

The new semantic recipe uses the existing two-call material time proof:

```yaml
time_selection:
  mode: detection
  method: material
  call: 1
  payload: locus_alerts
  complete: true
  time_scale: utc
  detection_identity: detection.identity.source_id
```

The optional `detection_identity` field requires an existing mapped origin source
ID in the same detection evidence payload. For this declaration it resolves to
`properties.ztf_candid`. Its compiler, planning and runtime representation extend
the current temporal proof; they add no new architecture layer, IR operation,
user keyword, ontology leaf or response mapping. Other providers retain the
default proof behavior when the field is absent.

Membership still requires finite ordinary photometry and a finite observation
time. An upper-limit-only record is not a witness. Photometry without the declared
origin identity cannot establish a ZTF witness: if no valid positive witness
exists, such incomplete evidence raises an explicit temporal error. The source ID
check does not remove measurements from surviving Portfolios.

Required object-payload validation now accepts native attribute-based client
records, matching the existing payload resolver. It still rejects null/scalar
responses. Missing or malformed `alerts` is distinct from a present empty list.
Empty complete history, an upper-limit-only history, and empty discovery are
valid negative/empty results. A request failure or unproven evidence cannot become
a successful empty result.

Full history can satisfy a subsequent lightcurve Get through the existing
execution reuse proof. The reused raw executions include rejected candidates,
but their semantic material is restricted to the selected identities. Continuation
replays the original histories and clock without repeating discovery or history
retrieval. Existing filter barriers retain their current binding policy.

## Contract audit

The repository still pins `antares-client==1.14.0`. Read-only source inspection of
[official tag `944197ad`](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/tree/944197ad2bdae5b46641ddf5f76711e1e327e6f0)
establishes:

- `search.py` looks up the ZTF identity and returns its rich Locus.
- `models.py` documents the associated alert list and the timeseries containing
  all historical alert data. `Locus.alerts` loads and caches this alert list from
  the locus's alerts endpoint; the selected `lightcurve` is a separate representation.
- `_api/api.py` raises on HTTP errors. Discovery follows all `links.next` pages.
  The alert-list accessor is the client's associated-history contract, not a
  user-limited query or the selected client lightcurve.

Completeness here means the provider's reported associated history under that
contract, not all observations ever made or an atomic cross-call snapshot. The
deployed service was not probed. A future paginated/truncated alert-list contract
would require changing the accessor/proof before claiming negative coverage.

The immutable [ZTF fixture audit](../tests/fixtures/antares/ztf/README.md) records
316 alerts, including 70 candidate measurements and 246 upper limits; the
selected client lightcurve contains only 280 of those alerts. All 70 magnitude
rows in that frozen history contain `ztf_candid`. Neither the selected lightcurve
nor total-alert/oldest-alert/newest-alert summaries substitute for detection
membership. This branch preserves all frozen evidence.

## Remaining ANTARES work

06d will address detection extrema for first/last and global latest. Semantic
first/last/latest and temporal cone discovery remain unactivated in this branch.
There is no new Rubin discovery or classification join; those retain the agreed
end-of-series consultation. Continue the remaining material, result-access and
acceptance milestones afterward.

## Local handoff

No project imports, tests, builds, apps or live requests ran here. Python AST,
YAML, whitespace and bundle verification accompany the branch.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_antares_time.py \
  tests/test_antares_semantic_search.py \
  tests/test_orchestration_elasticsearch_bindings.py \
  tests/test_orchestration_time_membership.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-discovery-06c-tests.log
```

The synthetic native models exercise closed boundaries, temporal gaps, limit-only
and empty histories, mixed evidence with missing origin identity, required-call
failure, incomplete negative coverage, plan serialization, full measurement
retention, survivor-only history reuse, offline normalization and pinned-clock
continuation. Native lightcurve access deliberately raises in the fixture, proving
that this selected representation cannot supply the membership evidence.

Fixture call counts describe native client entry points. A real rich Locus can
perform additional HTTP requests for its lazy relationships. Keep provider live
acceptance separate from these offline regressions. DSL CI already includes the
new module through its orchestration glob; no further intermediate CI is needed
before the extrema milestone if the focused local suites pass.
