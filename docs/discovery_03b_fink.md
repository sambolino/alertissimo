# Activate audited Fink ZTF class/time discovery

Fink ZTF now declares a `semantic_search` recipe for the existing `latests`
endpoint. The public example can validate, plan, bind, execute, and normalize
through the existing facade:

```text
objects from ztf via fink
within 7d
where classification.best.class = "SN candidate"
```

This is PR **03b** of the discovery integration plan, based on merged PR #296,
main `1ced30e`. The existing DSL, WorkflowIR, recipe compiler, binder, executor,
predicate evaluator, and Portfolio remain the architecture. No new layer, DSL
keyword, provider-specific planner branch, or replacement result model is added.

## Admitted scientific population

The recipe admits equality to **`SN candidate`** and **`Early SN Ia candidate`**.
These are audited ordinary Fink class-index labels. `within` constrains the
observation JD of class-indexed alerts, not object first detection, processing
time, or the object's latest current classification. Candidate identity remains
`(ztf, object_id)`; repeated alerts stay attached to that object.

The physical class parameter accepts more aliases than this scientific binding.
TNS/SIMBAD aliases and special SLSN/CTA tables have different population or grouping
semantics. Other labels remain deliberately deferred, with the admitted values
included in the required-parameter diagnostic. Adding a verified label later is
a declaration change after its route is audited; a physical enum is not narrowed
to pretend the API itself accepts only these two strings.

The existing predicate binding gains two optional, compiled attributes:

```yaml
predicate_bindings:
  latests:
    - path: classification.best.class
      operator: "="
      parameter: class
      values: [SN candidate, Early SN Ia candidate]
      exact: false
```

`values` restricts this binding to a finite, typed scalar domain. It is checked
at registry compilation against the physical parameter type, then during the
existing predicate realization. `exact: false` sends the selector upstream while
retaining the same predicate for local evaluation against returned normalized
evidence. Defaults are unrestricted values and `exact: true`, preserving existing
bindings. This is declaration metadata, not a new expression language.

The stream selector alone cannot manufacture scientific classification material.
Returned `v:classification` must satisfy the predicate; missing or different
classification yields no surviving candidate. This recheck does not reconstruct
historical classifier versions or discover alerts absent from Fink's class index.
The service's indexed population and its returned classification evidence remain
the stated contract, rather than a claim about every object's current class.

Missing class, unsupported standalone labels/operators, wrong qualifiers,
conflicting eligible equalities, and OR/NOT without an independently eligible
required class binding fail admission before transport. Existing Boolean and
conjunction rules are preserved. Mapped residual conditions can further select
candidates locally.

## Time, limits, and provenance

`startdate` and `stopdate` consume the whole existing `step.time_context` through
the UTC ISO transform from 02b. Relative bounds use one occurrence clock, which
is retained for continuation. Explicit aware bounds preserve their UTC instant.
No date-only rounding, boundary shift, TAI conversion, or time subdivision is
introduced. Bound strings are passed directly to Fink's native JD range scan;
this branch does not invent a new inclusive/exclusive boundary convention.

With no `within`, the truthful physical start default and provider-owned current
stop remain unchanged. Unsupported offsets, sampling, naive/open/mixed contexts,
untranslated criteria, and global `latest N` remain deferred. No arbitrary default
class is provided.

GET, default `n=100`, and default JSON are unchanged. All columns are retained so
the class and residual evidence are available; the recipe adds no projection or
trend. The 03a guard runs **before** local residual pruning: reaching the physical
cap raises an explicit incomplete-result error, even if most returned candidates
would later be discarded. A busy seven-day search can therefore fail visibly;
it is not advertised as exhaustive pagination. Narrow the interval if necessary.

Explicit raw exports remain physical endpoint operations and carry no completeness
guarantee. No global `latest N`, cursor, or window-subdivision implementation is
inferred from `n`.

Scientific selection retains whole candidate Portfolios. A subsequent lightcurve
retrieval receives only surviving IDs and retains all returned measurements,
including measurements outside the discovery interval:

```text
objects from ztf via fink
within 7d
where classification.best.class = "SN candidate"
filter measurement@ztf:fink.quality.real_bogus >= 0.9
with lightcurve via fink
with classification via fink
```

The explicit classification clause above keeps that retrieval after the filter.
Without an explicit clause, the existing DSL inserts its implicit classification
requirement for a general `where`. That can cause an additional `objects` request;
this branch does not introduce fixed-producer discovery reuse or change that DSL
lowering contract.

Qualified `classification@fink` references need no invented server classifier
parameter when the mapped leaf proves one fixed producer. Mixed/dynamic producers
still require their declared server selector. During local rechecking, legacy
`classification@fink` records without a channel suffix obtain that channel only
from **their own execution provenance**. An explicit suffix takes precedence;
another broker in the Portfolio cannot supply the missing channel. Records and
audit provenance are not rewritten.

## Fink support matrix for this branch

| Survey / request | Status | Reason |
| --- | --- | --- |
| ZTF, either admitted class, relative UTC window | Activated | Ordinary alert class index, whole-context binding, response recheck, cap guard |
| ZTF, either admitted class, paired aware absolute bounds | Activated | Same physical route; UTC instants forwarded unchanged |
| ZTF, class without a time clause | Activated with existing physical defaults | Same cap guard; default historical start and provider stop |
| ZTF, other classes, catalogue aliases, grouped routes | Deferred | Scientific population / completeness not admitted by this binding |
| ZTF, trend/criteria, global latest, unsupported time forms | Deferred | No declared scientific translation or selection proof |
| Rubin/LSST, arbitrary classification equality with a window | Deferred | API uses filter tags, not equivalent arbitrary class labels; time-scale audit also required |
| Existing cone, lookup, and retrieval operations | Existing support retained | Their independent recipes and mappings remain in place |

The earlier [03a audit](discovery_03a_fink_result_limit.md) records transport,
grouping, and post-filter findings. Primary source snapshots inspected without
running upstream code:

- [Object API `a10923b`](https://github.com/astrolabsoftware/fink-object-api/tree/a10923b0626aa7b73ef41e684e198c96713f2dd3),
  `ztf/latests/{api,utils}.py`, `apps/utils/decoding.py`, and `lsst/tags/{api,utils}.py`.
- [Broker `d368cb1`](https://github.com/astrolabsoftware/fink-broker/blob/d368cb1526c89fcd3c62bf7c4a9627e3f117f845/bin/ztf/archive_index.py),
  class index built from class, observation JD, and object ID.
- [Filters `6be6efc`](https://github.com/astrolabsoftware/fink-filters/blob/6be6efc60956c99179bc400693ae8b87f19663e1/fink_filters/ztf/classification.py),
  the final Fink classification function and admitted label spellings.
- [Official class-search guide](https://doc.ztf.fink-broker.org/services/search/classsearch/).

## Local verification

No tests, builds, apps, or live broker requests were run here. Python AST, YAML,
whitespace, and Git bundle checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_fink_semantic_search.py \
  tests/test_fink_ztf_authoritative_payloads.py \
  tests/test_fink_registry_architecture.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_required_predicate_bindings.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_endpoint_pagination.py \
  tests/test_orchestration_residual_pruning.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_dsl_predicate_realization.py
```

The immutable `latests.json` capture contains ten Early-SN alerts for seven
objects. Replays verify binding, identity, response recheck, residual selection,
and continuation. Its original request was capped at ten: replaying those rows
with a larger fixture ceiling does not prove historical population completeness.
The exact SN query uses unchanged recorded rows selected from `objects_core.json`
as a **synthetic class response**, then the full recorded object response to check
that downstream retrieval retains every measurement. Multi-object retrieval
fixtures route selected recorded class rows as object responses; they do not claim
to represent complete upstream lightcurves. Synthetic missing/different-class,
empty, and saturated responses exercise the corresponding failure paths.

DSL CI includes the new facade regression module; existing semantic-registry CI
retains the provider and mapping contracts. The facade suite is not duplicated in
the registry job. There is no new runtime dependency or package resource. A real
seven-day result and provider availability still require local live evidence.
After this branch is merged, the next provider milestone is ALeRCE class/time
discovery (04).
