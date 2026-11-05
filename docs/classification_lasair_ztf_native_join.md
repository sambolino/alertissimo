# C7b: native Lasair ZTF Sherlock discovery

This extends the existing Lasair ZTF semantic-search recipes with one audited
object/context join. It does not define a shared class taxonomy. In particular,
Sherlock's `SN` is a contextual galaxy association, not a physical SN subtype or
an interchangeable Fink/ALeRCE prediction.

```text
objects from ztf via lasair
last within 7d
where classification@sherlock:lasair.best.class = "AGN" and summary.detection_count >= 5
latest 10
with lightcurve via lasair
```

This selects the current Sherlock `AGN` label and provider-reported count on
objects whose latest reported detection falls in the window. Pagination completes
before normalized predicate/time rechecking and object ranking. Downstream
lightcurves retain the complete returned history, including outside-window
measurements. It does not reconstruct the class known at a past alert epoch.

## Exact boundary

| Contract | Admitted | Deferred |
| --- | --- | --- |
| Native Sherlock label | Exact DSL `=` to `AGN`, `BS`, `CV`, `NT`, `ORPHAN`, `SN`, `UNCLEAR`, `VS`; generic, Sherlock-qualified and Lasair-qualified references | Literal `NULL`, aliases, lower-case labels, arbitrary text, `!=`, ordered string comparisons |
| Conditions | Positive label equality, alone or AND existing numeric summary comparisons | OR/NOT, partially translated conditions, score/probability filters, other producers and joined tables |
| Population and order | Unwindowed eligible class search, existing first/last/detection windows, complete object pagination, local `latest` after selection | Bare unconstrained scans; database snapshot isolation while the population changes |
| Evidence | Current raw Sherlock class, reliability as `best.score`, description, with existing query-row provenance | Invented probability, physical-class reinterpretation, cross-broker calibration or consensus |
| Surveys | Lasair ZTF only | Lasair Rubin/LSST: its schema and join need their own audit |

`NULL` is deliberately not a string search alias or a missing-value operator.
Absent context rows and SQL NULL classes cannot satisfy the admitted positive
equality. An empty complete scan is a valid empty result; provider error objects
and pagination-policy exhaustion are failures, not empty populations.

## Join and source evidence

Read-only inspection fetched official `lsst-uk/lasair4` on 2026-11-05 at
[`29379e154e6d46fc5099c0056e21f388e96623e3`](https://github.com/lsst-uk/lasair4/tree/29379e154e6d46fc5099c0056e21f388e96623e3):

- [`common/schema/sherlock_classifications.sql`](https://github.com/lsst-uk/lasair4/blob/29379e154e6d46fc5099c0056e21f388e96623e3/common/schema/sherlock_classifications.sql)
  declares `objectId` as the primary key, a text class and integer reliability.
  Together with the [objects primary key](https://github.com/lsst-uk/lasair4/blob/29379e154e6d46fc5099c0056e21f388e96623e3/common/schema/objects.sql),
  this establishes at most one joined row per object in the audited schema; context cannot multiply identities.
- [`common/schema/sherlock_classifications.py`](https://github.com/lsst-uk/lasair4/blob/29379e154e6d46fc5099c0056e21f388e96623e3/common/schema/sherlock_classifications.py)
  documents the native context labels and names classification reliability,
  without defining it as a probability. The public [Sherlock documentation](https://lasair.readthedocs.io/en/main/core_functions/sherlock.html)
  explains the contextual associations, including the meaning of `SN`.
- [`webserver/lasair/query_builder.py`](https://github.com/lsst-uk/lasair4/blob/29379e154e6d46fc5099c0056e21f388e96623e3/webserver/lasair/query_builder.py)
  always includes `objects`. Selecting `sherlock_classifications` adds an inner
  equality join on objectId. A physical request naming only Sherlock would
  therefore still join objects. The recipe names both tables explicitly.
- [`webserver/lasairapi/serializers.py`](https://github.com/lsst-uk/lasair4/blob/29379e154e6d46fc5099c0056e21f388e96623e3/webserver/lasairapi/serializers.py)
  preserves selected/conditions/table inputs, separate limit/offset, account
  limit clamping, dictionary result rows and object-shaped errors.

The emitted condition includes the same identity equality explicitly. Lasair's
automatic equality is redundant and compatible. The projection selects one
`objects.objectId`, six object-summary fields in total, and the Sherlock class,
reliability and description. Unselected possible mappings are not call evidence.

## Existing boundaries, extended narrowly

The physical query endpoint is unchanged. Provider capabilities author an
optional `sql_join` on the discovery call, with left/right qualified object keys
and an explicit `right_unique: true` assertion backed by the source audit.
The loader admits exactly that two-table projection, one required conditions
parameter, mapped identity ordering and automatic pagination. It rejects missing
uniqueness, incompatible keys/tables/projection and fixed offsets. This is a
reviewed provider contract, not runtime schema introspection.

Cross-table predicate bindings are unavailable on ordinary object-only calls.
A joined recipe is eligible only when the whole predicate translates and a
positive condition uses its joined material. Summary-only searches therefore
retain objects with no Sherlock row, rather than losing them to an inner join.
There is no endpoint alias, raw-SQL IR, new operation, or provider-name branch in
the planner.

SQL symbolic equality uses the existing finite `values` domain with a restricted
uppercase symbolic alphabet, no arbitrary string interpolation, no subtraction,
and an explicit `exact: false` residual contract. The API's double-quoted label
syntax matches its query builder and documented examples. Database collation can
admit extra rows, so every returned class is rechecked with the original DSL
predicate. This does not prove that a deployment returned every eligible row.
Numeric bindings keep their existing finite-number and unit-conversion rules.

The complete returned population is scanned in `objects.objectId` order. The
audited unique join preserves the existing object pagination/recency contract;
no `latest` limit is pushed into SQL. First/detection windows do not bound an
object's last detection, and `latest` retains its established discovery-recency
meaning. Continuation reuses the prior population and reference clock.

## Verification and checkpoint

`tests/test_lasair_semantic_search.py` extends the existing offline suite. Its
two-table fixture uses explicitly synthetic context rows and keys based on an
unchanged captured summary template. SQLite independently executes the compiled
join, condition, order and pages. `NOCASE` deliberately returns a broader label
population than Python to exercise normalized rechecking. These are not new
broker captures or verification of deployed MySQL SQL mode/collation.

The regressions compare native and complete local filtering for all eight
labels, including absent/NULL/mismatched labels, qualified producers, count
conjunctions, all three window modes, recency ranking, full histories,
continuation, complete empty results, policy failures and declaration rejection.
The emitted parameters were also accepted by the audited official query
builder in a read-only local check. The DSL workflow already includes this
module; no CI path change is needed.

Run the focused modules in the handoff before merging. Because this slice extends
shared recipe validation and predicate realization, run DSL and semantic-registry
checkpoints on the merged integration SHA. Keep #329 draft; final main-target
verification remains required. No authenticated live broker retrieval was run
while preparing this slice.

Preparation checks on this slice:

- The focused Lasair/capability suites passed 138 cases, including 126 in the
  Lasair module (55 existing cases plus 71 new cases).
- The union of the DSL and semantic-registry workflows covered 2,481 cases:
  2,419 parallel cases passed initially; the remaining existing architecture
  expectation was updated for query class/description mappings and its entire
  six-case module passed on recheck. All 61 shared-fixture cases also passed.
  No production change was needed after these checks.
- The installed-wheel release-package check passed, including packaged runtime
  resources and the public static/cone/enrichment planning probes.
- Whitespace checks passed. The handoff's nine-module local command collects
  302 cases; its Lasair module must collect 126 to confirm the bundle was imported.

## Native deployment acceptance

The existing discovery runner now includes `lasair-ztf-sherlock`. It uses
`last within` (one hour by default), native Sherlock `AGN` equality, global
`latest`, and full lightcurves for survivors. The cone scenarios' `--time-mode`
option does not change this scenario's last-detection contract.

PASS requires a nonempty result, the discovery query's actual joined tables
and class selector, its own normalized Sherlock AGN evidence, the requested
candidate limit, and returned lightcurve material. Empty complete populations
remain SKIP; use `--require-all-pass` when collecting acceptance evidence.
Provider errors, policy exhaustion and outages retain the existing status rules.

The new offline replay uses synthetic summary/context/history rows and checks
outside-window history retention. Run the new scenario explicitly with
`--validate-only` first, then live using the existing `LASAIR_ZTF_TOKEN`.
No deployed PASS is claimed by preparing this addition.
