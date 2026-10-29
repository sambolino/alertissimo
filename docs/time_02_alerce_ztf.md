# Activate ALeRCE ZTF temporal candidate selection

Based on merged Time 01b PR #306, main `37ba25c`. Its fan-out, continuation,
and final semantic material fixes are present in this base.

ALeRCE ZTF semantic and cone discovery now admit these distinct operations:

| Intent | Discovery request | Membership evidence |
| --- | --- | --- |
| `within 7d` | `lastmjd=[start_mjd]` | Required per-object `query_lightcurve`; at least one ordinary detection in `[start,end]` |
| `first within 7d` | `firstmjd=[start_mjd,end_mjd]` | Corresponding authoritative object first-detection timestamp, rechecked locally |
| `last within 7d` | `lastmjd=[start_mjd,end_mjd]` | Corresponding authoritative object last-detection timestamp, rechecked locally |

Explicit `within ["start","end"]` uses the same closed-interval rules. A relative
window ends at the occurrence's pinned now. Scientific syntax, IR Steps,
Portfolio models, and the existing endpoint/planner/binder/normalizer separation
stay in place. No new architecture layer, dependency, or public keyword is added.

## Why default within needs a history call

An object can have observations before and after an interval but none inside it.
Default within therefore does not mean that its first or last observation falls
inside the interval. The discovery minimum on **last** is only a safe superset:
do not apply the interval end as a maximum on last, since a newer observation
must not exclude a genuine historical witness.

This branch deliberately uses the verified one-sided `lastmjd >= start` native
filter. It does not invent an open-lower-bound representation for `firstmjd <=
end`, or use an arbitrary numeric epoch as a substitute. It may retrieve a wider
population than a two-sided summary-overlap optimization. Historical requests
can be expensive; a cone and supported discovery predicates can narrow them.
The existing execution pagination policy still fails explicitly at its limit.

Discovery is fully paginated before required histories are requested. Negative
membership uses the audited full, uncapped legacy ZTF lightcurve route, not an
alert packet's limited previous-candidate history. Non-detections do not supply
a positive witness. Missing/malformed evidence and required-call failures are
errors. A present empty detection list is a valid negative result. This describes
the broker's available population/history, not a guarantee of every physical
observation ever taken or an atomic snapshot across requests.

Survivors retain all returned measurements, including dates outside the interval.
An explicit later `with lightcurve via alerce` reuses compatible required history
and preserves the existing supplement policy: optional singular forced photometry
is retained only for one explicit target, not for a targetless population request.
Its omission is a planning decision, not an optional-call failure. Reuse and
incremental continuation retain the selected identities and the original clock.
First/last discovery itself needs no per-object history requests.

## Range composition and evidence shape

The existing request-transform registry adds a pure `object_mjd_range` encoder.
The physical declaration identifies first or last. It encodes the resolved
whole TimeContext, or the already-supported explicit numeric `>=` literal.
The compiler only permits the latter on its matching mapped summary field.
Unwindowed explicit predicates keep their existing scalar planning value and
physical `[minimum]` encoding. Rubin's declarations are untouched.

When an explicit minimum and a temporal window address the same parameter, the
binder intersects the two finite inclusive ranges. For example, a last window
of `[59010,59020]` with `summary.time.last_mjd >= 59015` sends `[59015,59020]`.
Repeated/conflicting semantic leaves retain the existing residual behavior;
other operators remain normalized residuals. Fixed constants cannot use this
exception to override a predicate. A contradictory intersection remains
`[higher_minimum,lower_maximum]`; the audited server applies both comparisons
and returns no rows, rather than widening or dropping a bound.

The existing temporal proof also carries the mapped payload path, compiled from
its actual evidence fields. Staged and offline normalization check that the
evidence collection is present with the expected shape before interpreting an
empty collection as absence. This distinguishes `detections: []` from a missing
branch, `detections: null`, or an error object. It validates the declared evidence
branch, not unrelated optional response fields.

## Scope of latest and other providers

First/last can use the existing proven **single-call** ALeRCE ZTF latest contract;
temporal and residual checks precede global object ranking. Default within is
composite and `latest N` remains explicitly deferred until the scheduled shared
latest-admission milestone. No per-page or per-history top-N shortcut is added.

Rubin within remains deferred without its own time-scale and discovery proof.
Lasair ZTF is next, followed by Fink ZTF and the shared/provider latest branches.
Classification joins and remaining Rubin discovery stay at the end for the
agreed discussion before implementation.

## Source audit

Read-only inspection used these authoritative sources; no client code was run:

- The official `alerce==2.3.1` wheel, SHA-256
  `30efbcd42e1a92459816ec068af0d6252ddeaf49697f6d1b62e54455d3fccd3a`:
  `common_search.py` routes explicit survey ZTF to the legacy client;
  `ztf_search.py` sends object filters as supplied and retrieves the object
  lightcurve without page/row-limit arguments.
- [ALeRCE web-services, pinned `62bc0de`](https://github.com/alercebroker/web-services/tree/62bc0defe3aa3802f28cd9c293f4793ce2266fb6):
  `alerts-api/src/core/astro_object/domain/astro_object_service.py` applies
  inclusive first/last minimum and optional maximum comparisons.
  `api/resources/astro_object/parsers.py` accepts repeated floating-point range
  values without replacing contradictory ranges. `core/light_curve/domain/`
  and `infrastructure/repository.py` retrieve the object's detections and
  non-detections without a row-limit slice.
- [ZTF Science Data System explanatory supplement](https://irsa.ipac.caltech.edu/data/ZTF/docs/ztf_explanatory_supplement.pdf)
  describes the alert observation date at exposure start. The
  [Caltech/IPAC ZTF image example](https://caltech-ipac.github.io/kete/auto_examples/plot_comet.html)
  explicitly reads the exposure `OBSJD` on the UTC scale. This activation uses
  the legacy ZTF UTC MJD convention, not heliocentric timestamps or Rubin TAI.
  Existing ALeRCE mappings use `mjd`, `firstmjd`, and `lastmjd`, not the separate
  packet-history `mjdstarthist` / `mjdendhist` fields.
- The committed ALeRCE ZTF captured `query_objects.json` and
  `query_lightcurve.json` retain their original bytes. A recorded-response case
  selects around one captured detection and checks payload/record preservation.

## Local verification handoff

No tests, builds, project imports, app runs, or live broker calls ran here.
Python AST, YAML syntax, Git whitespace and bundle checks are the offline checks.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_alerce_time.py \
  tests/test_orchestration_time_membership.py \
  tests/test_alerce_semantic_search.py \
  tests/test_discovery_time_bindings.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  tests/test_recipe_registry.py \
  tests/test_request_transforms.py
```

The new orchestration module is already included by the DSL CI glob. Synthetic
cases cover all three modes through semantic/cone discovery, historical gaps and
newer observations, inclusive bounds, explicit predicate intersection, complete
pagination, malformed/missing/empty evidence, measurements retained on reuse,
continuation without repeated calls, and native temporal checks before latest.
The synthetic shared-time fixture now isolates itself from production temporal
alternatives. The old ZTF blanket-deferral assertion is replaced by concrete
ZTF activation cases; its Rubin safety assertion remains.
