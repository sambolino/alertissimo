# Fink ZTF temporal selection and integration workflow

Based on merged Time 03b, main `7536b2d` / PR #309. The integration bootstrap
commit creates `integration/discovery-completion` and excludes that exact PR base
from the three automatic CI workflows. Small feature PRs target that branch and
are squash-merged after focused local checks. Manual CI remains available; the
final PR into main runs CI normally. See the updated
[integration plan](discovery_integration_plan.md#verification-and-merge-discipline).
Remove the temporary branch exclusions on the integration branch just before
opening that final PR, as specified in the plan.

Time 04 is `feat/time-04-fink-ztf`, based on that bootstrap. Everything uses the
existing recipes, temporal encoder, capability compiler, staged execution,
normalization, and Portfolio. There is no new architecture layer, IR operation,
dependency, user keyword, provider planner branch, or broker request here.

## Admitted behavior

```text
objects from ztf via fink
within 7d
where classification.best.class = "SN candidate"
with lightcurve via fink
with classification via fink
```

The existing admitted ordinary class routes (`SN candidate`, `Early SN Ia
candidate`) now declare a native detection-window proof on the actual `latests`
payload. A candidate must have an ordinary mapped detection at a UTC MJD inside
the original closed interval. Summary history overlap, an upper limit, or another
execution's measurement is not that witness. Missing temporal evidence is unknown
and fails explicitly when no valid witness exists. Empty native discovery is a
valid empty result. Returned classification still undergoes its existing residual
recheck; special catalogue/grouped class routes remain outside this admission.

The window keeps relative intent and one pinned occurrence clock. An absolute
window retains its original instants and UTC offsets. Staged execution and later
normalization use the same temporal proof. Only surviving IDs feed subsequent
retrievals, and survivors retain every returned measurement, including those
outside the interval. Continuation replays the prior physical prefix and keeps
its reference time.

The unwindowed recipe remains separate and uses the existing physical defaults.
It does not acquire a window or a completeness claim by omission. Direct physical
requests preserve their explicit parameter values.

## Why the physical request has an envelope

The API constructs class-index keys from class, observation JD, and object ID.
Its reversed range scan supplies bare decimal JD prefixes, not numeric inclusive
comparisons. The inspected Lomikel client starts at the bare upper prefix and
stops at a byte-incremented lower prefix. Suffix-bearing boundary alerts can be
excluded; incrementing a short decimal prefix such as `2459010.5` to
`2459010.6` can move the lower cutoff by 0.1 day. A one-microsecond/one-second
epsilon would not cover that behavior for arbitrary bounds.

The existing `time_bound` encoder gains optional finite nonnegative
`padding_seconds`, default zero. Only Fink ZTF class-search bindings opt into
10800 seconds (three hours) outward at each edge. This exceeds the decimal
prefix's 0.1-day step for ZTF's positive, fixed-width JD range. Exact closed
scientific bounds remain unchanged and are rechecked against returned detections;
the extra alerts cannot qualify an object by themselves. The compiler rejects
padded discovery bindings without `time_selection` evidence. Invalid options
fail at registry compilation; datetime overflow fails during binding.

The existing JSON cap guard runs before residual or temporal pruning, including
for margin-only alerts. A saturated response is explicitly incomplete. There is
no cursor, retry, sampling, or time subdivision. The envelope may therefore make
a previously near-cap request fail conservatively; it does not silently reduce
the requested scientific population. The claim covers the broker's admitted
indexed class population, not all observations ever made or model-version parity
between historical indexing and current classification decoding.

## Explicit deferrals

| Request | Result | Reason |
| --- | --- | --- |
| ZTF admitted class + default within | Activated with exact local recheck | Ungrouped class-index alert scan and cap guard |
| ZTF admitted class without a window | Existing physical-default behavior | No invented time context |
| ZTF semantic first/last within | Deferred before transport | An alert observation-time index cannot discover the complete first/last object population |
| ZTF cone with any within mode | Deferred before transport | Per-pixel internal limits, grouping and later geometric pruning can hide saturation |
| ZTF latest | Deferred for the scheduled selection milestone | `n` is an alert ceiling, not global object latest |
| Rubin temporal discovery | Deferred | Different tag/index and time-scale contracts need independent verification |

For example, an object first observed on 1 January can become an indexed SN on
10 January. Scanning the class index only during 1–7 January cannot find it for
`first within` that interval. Fetching histories for the IDs that were found does
not recover the missing candidate. Per-alert `jdstarthist` / `jdendhist` values
also do not prove a unique current object first/last timestamp. This branch does
not relabel that alert window as an object-extremum query.

The existing unwindowed cone operation remains available under its original
contract. Adding a final-response row-count guard alone would not make its
temporal population complete: grouping and spatial pruning happen after the
internal cap.

## Source audit

Read-only inspection reconfirmed the official object API main at
[`a10923b0626aa7b73ef41e684e198c96713f2dd3`](https://github.com/astrolabsoftware/fink-object-api/tree/a10923b0626aa7b73ef41e684e198c96713f2dd3):

- `apps/routes/v1/ztf/latests/utils.py` converts UTC bounds to JD, scans the
  ordinary class table in reverse order, and does not group its alerts.
- `apps/routes/v1/ztf/conesearch/utils.py` caps scans per pixel, groups alerts,
  then applies the exact radius filter.
- `apps/routes/v1/ztf/objects/utils.py` fetches supplied IDs; it cannot discover
  objects omitted by a different index window.
- `apps/utils/decoding.py` retains individual ordinary class alerts; the optional
  color calculation adds derived columns rather than selecting the last object.
- `apps/utils/client.py` uses `com.Lomikel.HBaser.HBaseClient`. Its inspected
  [source at `2a05cad70f8969b74b228a9d6466192174cea073`](https://github.com/hrivnac/Lomikel/blob/2a05cad70f8969b74b228a9d6466192174cea073/src/java/com/Lomikel/HBaser/HBaseClient.java)
  establishes the prefix boundary issue. The installed service's actual JAR
  version was not probed; the envelope is conservative for this convention and
  for a numerically inclusive implementation.
- The existing broker audit at
  [`d368cb1526c89fcd3c62bf7c4a9627e3f117f845`](https://github.com/astrolabsoftware/fink-broker/blob/d368cb1526c89fcd3c62bf7c4a9627e3f117f845/bin/ztf/archive_index.py)
  establishes the class/observing-JD/object index construction.

## Local verification

No tests, builds, project imports, apps, or live broker requests ran here. Python
AST, YAML syntax, workflow-trigger inspection, whitespace, and Git bundle checks
are the available offline checks. Run locally and retain the log:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_fink_time.py \
  tests/test_fink_semantic_search.py \
  tests/test_discovery_time_bindings.py \
  tests/test_dsl_within_modes.py \
  tests/test_recipe_registry.py \
  2>&1 | tee /tmp/alertissimo-time-04-tests.log
```

The new synthetic prefix-scan fixture checks exact edges, different times of day,
physical overfetch, summary gaps, survivor-only retrieval, untrimmed histories,
empty and malformed evidence, saturation before pruning, pinned continuation,
and unsupported mode admission. Existing immutable captures remain unchanged.
The tests use the real endpoint registry and executor with an offline transport;
they are not new live captures and do not prove deployment availability.

After green focused checks, open this feature PR against
`integration/discovery-completion` and squash-merge it without automatic CI.
An intermediate shared DSL/registry CI checkpoint is recommended at shared latest
admission. The final integration-to-main PR must pass the applicable CI jobs.
The next feature is `feat/selection-01-latest-admission` from the updated remote
integration branch. Classification joins and additional Rubin discovery remain
reserved for the agreed discussion at the end.
