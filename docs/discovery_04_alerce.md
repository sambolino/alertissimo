# Complete explicit ALeRCE object-time and ZTF class discovery

ALeRCE discovery now binds explicit first/last-detection MJD minima to the native
range parameters on both surveys. ZTF also gains verified class and classifier
translations through the existing predicate bindings:

```text
objects from ztf via alerce
where classification@lc_classifier.best.class = "SN" and summary.time.last_mjd >= 61200 and summary.time.last_mjd <= 61207
with lightcurve via alerce
```

The numeric dates illustrate a historical **object-summary** interval, not a
recommended live interval. Choose the scientific interval explicitly. This is
PR **04**, based on merged Fink PR #300, main `9c09896`. No architecture layer,
DSL keyword, provider-specific planner branch, or replacement result model is added.

## Time meaning and encoding

`firstmjd` and `lastmjd` filter an object's first/latest detection in its current
summary. An object can have an alert inside a historical window and a later
detection outside it. Filtering its latest time would incorrectly exclude it from
that historical alert population. **Generic `within` therefore remains deferred.**
This branch does not choose its time axis, reinterpret TimeContext, or infer a
Rubin time scale from a column named MJD. Explicit numeric predicates use the
provider's reported scale without a clock, date conversion, or boundary shift.
PR 02b remains the clock/window mechanism where window equivalence is established.

The native first/last range parameters were incorrectly declared scalar numbers;
the inspected client and backend accept `[minimum]` or `[minimum, maximum]`.
Both endpoint declarations now accurately describe arrays.

| Scientific condition | Physical request | Residual |
| --- | --- | --- |
| `summary.time.first_mjd >= X` | `firstmjd=[X]` | None for this atom |
| `summary.time.last_mjd >= X` | `lastmjd=[X]` | None for this atom |
| Time with `>`, `<`, `<=`, `=`, `!=` | No pushdown for this atom | Original comparison |
| Minimum plus upper bound | Minimum only | Upper bound after complete retrieval |
| Conflicts, OR, NOT | Existing realization rules | No invented range algebra |

The plan retains a scalar predicate literal. The existing binder encodes it into
an array using endpoint `binding` metadata, the single `semantic_predicate`
operand, and a registered pure `numeric_lower_bound` transform in the existing
request-transform module. The compiler checks the adapter, array type, and `>=`
operator together. Missing values, booleans, strings, and non-finite numbers fail
encoding; callers cannot supply a runtime override for the planned literal.
No arbitrary callable loading is introduced.

Upper-only or historical upper-bound searches can require many pages because the
upper bound stays local. Results must be exhausted before residual pruning and
global latest selection. Reaching the existing execution-policy limit remains an
explicit error. No successful truncated population or snapshot isolation is claimed.

## Classification and evidence

ZTF class equality binds `class_name`; a producer qualifier or producer-name
equality binds `classifier`. The public Python client owns its `class_name` to
legacy REST `class` rename. No default class/model is invented. The audited
backend's class/model filter path uses ranking one when ranking is absent.
Both new ZTF bindings retain their original condition for local evidence checks:
null or unrelated class fields cannot be replaced by the requested label.

ZTF probability conditions stay local in this branch. The audited legacy
probability-only route does not establish the same ranking restriction as its
class/model route, so a broad new probability pushdown is not added. Existing
Rubin class/model/probability translations stay unchanged.

Rubin `query_objects` already returns first/last MJD fields. They now populate the
existing summary leaves so residual time comparisons have actual evidence. Only
those two entries leave the unmapped inventory. Counts and other duplicate-context
decisions remain independent. Two classifier rows for one object retain their
versions and row ownership; repeated summary times do not create another candidate.

Existing recipes still select `query_objects`. Physical survey identity, defaults,
pagination, partitioning, and selection retain their existing owners. ZTF latest
selection runs after complete discovery and residuals. Rubin latest retains its
existing deferral. Object selection keeps whole candidates and does not trim a
subsequently fetched lightcurve.

| Request | Support |
| --- | --- |
| ZTF class/model equality with explicit object-time minima | Activated with returned-evidence recheck |
| ZTF probability with class/model selection | Local residual |
| Rubin existing class/model/probability plus explicit object-time minima | Activated using reported MJD values |
| Explicit time upper bounds and other comparisons | Local residual after full retrieval |
| Generic within / arbitrary historical alert availability | Deferred; no equivalent summary translation established |
| UTC date conversion to Rubin's time scale | Deferred; no scale inference |

## Source audit

Read-only inspection used the official `alerce==2.3.1` wheel, SHA-256
`30efbcd42e1a92459816ec068af0d6252ddeaf49697f6d1b62e54455d3fccd3a`, without
installing or running it: `common_search.py` routes the surveys, `ztf_search.py`
documents ranges and renames the class argument, and `ms_search.py` admits both
range names for Rubin.

The official backend snapshot
[`alercebroker/web-services` `62bc0de`](https://github.com/alercebroker/web-services/tree/62bc0defe3aa3802f28cd9c293f4793ce2266fb6)
provides the comparison evidence:

- `alerts-api/src/api/resources/astro_object/parsers.py`: repeated float time values.
- `alerts-api/src/core/astro_object/domain/astro_object_service.py`: inclusive
  object bounds and conditional ranking-one selection for class/model requests.
- `multisurveys-apis/src/object_api/models/filters.py` and
  `services/statements_sql.py`: range arrays and inclusive object-time comparisons.

The [client reference](https://alerce.readthedocs.io/en/latest/apis.html) and
[ZTF object model](https://alerce.readthedocs.io/en/stable/models/object.html)
document names and first/latest-detection meaning. Source inspection does not
prove that a deployed service is byte-identical to this snapshot. No broker calls
or new captures were made.

## Local verification

No tests, builds, apps, or live calls ran here. Python AST, YAML syntax, whitespace,
and bundle checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_alerce_semantic_search.py \
  tests/test_alerce_ztf_endpoint_contracts.py \
  tests/test_alerce_registry_architecture.py \
  tests/test_alerce_lsst_authoritative_payloads.py \
  tests/test_request_transforms.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_selection_recipes.py \
  tests/test_orchestration_classification_material.py \
  tests/test_dsl_predicate_realization.py
```

Facade regressions replay the recorded ZTF wrapper and Rubin bare-list shapes
through a fake client with explicit filtering/pagination. They cover scalar-plan
to array-binding round trips, residuals before latest selection, classifier
ownership, missing class evidence, policy limits, invalid encodings, and within
deferral. The positive ZTF class fixture clearly adds synthetic class fields to
recorded object statistics; those fields are not a new authoritative capture.
The lightcurve fixture samples unchanged first/last rows from each recorded branch
to keep this regression small; every returned sample measurement must survive in
the final Portfolio, including times outside the object-selection interval. It
does not claim that the reduced fixture is a complete live lightcurve.

DSL CI includes the new facade module once. Existing semantic-registry tests cover
the provider/mapping changes and expanded Rubin summaries. No new dependency or
package resource is needed. Live acceptance stays on the local machine and the
final handoff. Next: Lasair semantic discovery (05).

The ALeRCE architecture regression now permits value-encoder metadata only inside
physical parameter declarations, consistent with existing Fink/ANTARES usage. It
still rejects endpoint-level binding/planning declarations and nested semantic
input keys. This updates the physical-encoding boundary without removing its guard.
