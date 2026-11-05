# Fink latest: verified activation boundary

Branch `feat/selection-03-fink-ztf`, based on integration `9f4a7bd` after
PR #315's matrix correction. Target `integration/discovery-completion`.

## Outcome

Keep Fink ZTF `latest N` deferred before transport. This milestone audits the
proposed activation and adds a concrete regression for the reason it cannot yet
be declared. It adds no runtime logic, new architecture layer, endpoint, or
recency interpretation. Existing class discovery, default within, history
retrieval and continuation remain available under their existing contracts.

`latest N` means greatest overall object last-detection time among the qualifying
candidates, after population discovery and temporal verification. Fink's
`latests` name and its `n` argument describe an alert stream and a physical
ceiling; they do not implement this object selection.

## A counterexample below every response limit

Both candidates have a qualifying SN alert inside the requested interval:

| Object | Class-response alert MJD | Last MJD on that alert | Later archived alert MJD / class |
| --- | --- | --- | --- |
| A | 59011 | 59011 | 59019 / Unknown |
| B | 59012 | 59012 | No later row in this example |

Sorting the two class-response rows selects B. Retrieving the later history
reveals A's greater last date. The class response can be complete and far below
its cap while still lacking the ranking evidence. The test executes ordinary
class discovery and lightcurve retrieval with these synthetic rows through the
real registry/executor/normalizer and checks the differing normalized recencies.
The classification WHERE reference also emits an implicit classification Get.
That occurrence and the explicit lightcurve Get each use an `objects` request
bound to both candidates; they are not one request per object. The regression
checks all three semantic occurrences and both retrievals separately.
It is not a captured response or a claim that a particular live source changed
classification this way.

The mapped `summary.time.last_mjd` values remain useful per-alert evidence. Their
presence does not prove that a historical class response includes each object's
latest history snapshot. Keeping the original mappings preserves that evidence.

## Why an extra objects call is not an established fix

At the audited API revision, `objects` scans supplied object IDs in the main ZTF
table. Its shared client applies the server's `NLIMIT`; the repository config
sets 10000, but that is not a verified value for every deployment. The route
does not expose a result count override, cursor, pagination, or a guaranteed
latest-object-summary response. It does not establish a reverse scan with a
guaranteed newest record either.
The decoder sorts rows after retrieval; that cannot recover rows omitted by
the preceding scan limit.

There is consequently no sufficient completeness proof for a required history
call solely from successful HTTP status or from a small final JSON response.
Do not invent a physical `n` argument on `objects`, assume a fixed deployment
cap, or discard the existing discovery cap guard. A downstream `with lightcurve`
also occurs after discovery selection and cannot supply a missing planning proof.

Fink cone latest remains deferred separately: internal per-pixel caps precede
grouping and geometric pruning. Rubin's different tag/index/time contracts do
not inherit ZTF activation. No new Rubin discovery is implemented here.

## What would permit activation

Verify an object lookup that returns an authoritative latest timestamp for every
discovered ID, or a complete history contract with detectable truncation or
exhaustible pagination. Discovery must independently retain its complete
qualifying population and cap checks. Such evidence can then be represented in
the existing recipes and selection checks. Changing `latest` to mean latest
qualifying alert would require a separate scientific decision; this branch does
not make it implicitly.

This is a provider contract follow-up, not a reason to block the remaining
ANTARES, material inventory, result access and acceptance work. Carry the explicit
Fink limitation into the final support matrix. Classification joins and additional
Rubin discovery still require the agreed end-of-series consultation.

## Primary source audit

Read-only inspection on 30 October 2026 reconfirmed official Fink object API
main at `a10923b0626aa7b73ef41e684e198c96713f2dd3`:

- [Class extraction](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/routes/v1/ztf/latests/utils.py):
  the admitted ordinary route scans `ztf.class` by class and observing-JD range,
  sets the alert limit, and formats ungrouped alert rows.
- [Object extraction](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/routes/v1/ztf/objects/utils.py):
  one scan per object prefix, no newest-record selection or pagination protocol.
- [Object route arguments](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/routes/v1/ztf/objects/api.py):
  object IDs, optional extra material, columns and output format.
- [Shared client](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/utils/client.py)
  sets the limit from configuration; [repository config](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/config.yml)
  declares `NLIMIT: 10000`.

The deployed server configuration and responses were not probed. This audit
identifies absent guarantees; it does not assert that any particular live
object history was truncated.

## Local handoff

No project imports, tests, builds, apps or provider requests ran here. AST/YAML
syntax, whitespace and Git bundle checks are the available static verification.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_fink_time.py \
  tests/test_fink_semantic_search.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_dsl_live_material_lineage_matrix.py \
  2>&1 | tee /tmp/alertissimo-selection-03-tests.log
```

New cases cover both admitted classes, with and without a window, public and
direct planning deferral, no transport work for a rejected latest request, and
the normalized historical-recency counterexample. No intermediate full CI is
needed for this regression/documentation change.
