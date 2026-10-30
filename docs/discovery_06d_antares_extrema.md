# ANTARES first/last within from complete detection history

Branch `feat/discovery-06d-antares-extrema`, based on integration `20534f1` /
PR #319. Target `integration/discovery-completion`; squash after local checks.

This review implements first/last membership. Global latest ranking is a separate
06e review, keeping its completeness/ranking checks independent of this interval
membership change. The remaining integration milestones retain their order.

## Activated behavior

```text
objects from ztf via antares
where summary.position.ra >= 50.847 and summary.position.ra <= 50.849 and summary.position.dec >= 37.467 and summary.position.dec <= 37.469
first within 7d
with lightcurve via antares
```

Replace `first` with `last` to select by the last detection. The bounds are closed;
relative windows use the occurrence's fixed UTC clock, while absolute intervals
keep their authored instants. Both modes discover the existing coordinate
population and require complete alert history for every candidate.

First is the minimum and last is the maximum of that object's finite detection
times, independent of response order. Upper limits do not participate. A
candidate must have ordinary finite photometry and the mapped ZTF source identity
to contribute a detection. The time remains the existing mapped detection MJD;
no oldest/newest-alert timestamp is renamed or inserted into a summary record.
This describes the provider's reported detection history, not detections outside
its archive.

Selecting objects preserves all their measurements, including upper limits and
out-of-window detections. History execution reuse and pinned-clock continuation
use the same existing mechanisms as default within.

## Existing proof extension

The first/last recipes retain required `search` followed by
`get_by_ztf_object_id`, with material evidence at `locus_alerts`:

```yaml
time_selection:
  mode: first
  method: material
  call: 1
  payload: locus_alerts
  complete: true
  time_scale: utc
  detection_identity: detection.identity.source_id
  reduction: min
```

Last uses `mode: last` and `reduction: max`. The optional reduction is compiled
into the existing temporal proof and runtime model. It requires matching mode,
complete required history, mapped ordinary photometry, time and source identity
in the same payload. It cannot be used for a native summary date or incomplete
history. Runtime checks also reject a conflicting reduction proof.

An in-window detection alone is insufficient to establish the first or last
date. Any malformed time, photometry or required origin identity can hide a more
extreme detection, so such evidence remains unknown even when another valid
detection lies in the window. A complete empty/limit-only history has no first or
last detection and does not qualify. No records are removed from survivors.

Existing summary-based first/last provider proofs retain their behavior when
`reduction` is absent. This adds no new architecture layer, IR Step, DSL keyword,
ontology leaf, response mapping or network endpoint.

## Object coverage

For a singular object response with a declared detection source identity, the
compiler now records its root object identity and target parameter. The raw
history response must identify the object that was requested. A wrong-object
response fails instead of becoming an apparently complete negative history.
Existing batched root-field validation continues to validate its response array;
single-object client models use their public mapped attributes.

The completeness/source audit remains the pinned ANTARES 1.14.0 associated-alert
contract described in [06c](discovery_06c_antares_within.md#contract-audit). Frozen
captures and response mappings are unchanged. No deployed provider was queried.

Temporal cone discovery still needs an explicit ZTF identity-scope proof for the
native shared-survey cone population; coordinate discovery is the activated
path here. Review that alongside the remaining ANTARES selection work. Global
latest remains deferred until 06e. Classification joins and additional Rubin
discovery remain end-of-series consultation items.

## Local handoff

No tests, project imports, builds, apps or live requests ran here. Static AST,
YAML, whitespace and bundle checks accompany this branch.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_antares_time.py \
  tests/test_antares_semantic_search.py \
  tests/test_orchestration_time_membership.py \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_lasair_time.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-discovery-06d-tests.log
```

New cases distinguish min/max on unsorted histories, test both exact interval
edges, place upper limits beyond both extrema, preserve full survivor material,
reuse history without repeat calls, and replay the pinned clock. Malformed
history with another in-window detection remains unknown; wrong-object responses
and invalid reduction declarations fail explicitly. Existing ALeRCE/Lasair time
regressions cover unchanged native summary and other history contracts.

Keep the local-check/small-squash workflow. Run the next manual shared DSL
checkpoint after the 06e ranking milestone rather than repeating CI between
these adjacent selector changes.
