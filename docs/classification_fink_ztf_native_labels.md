# C7a — Audited ordinary Fink/ZTF class-index labels

Branch: `feat/classification-fink-ztf-native-labels`.
Base: `06393f9` on `integration/discovery-completion`, after C6 (#344).
Keep main-target #329 draft.

## Supported request

```text
objects from ztf via fink
within 7d
where classification.best.class = "Kilonova candidate"
with lightcurve via fink
```

The existing `latests` binding now admits the six additional ordinary native
labels: `Kilonova candidate`, `Microlensing candidate`, `Tracklet`,
`Solar System MPC`, `Solar System candidate` and `Ambiguous`. Together with
`SN candidate` and `Early SN Ia candidate`, these are the eight audited ordinary
labels in the inspected provider class list. General and scoped classification
conditions retain their existing semantics and producer/channel qualifiers.

These are literal upstream labels, not new Alertissimo class families. In
particular, the upstream label `Ambiguous` is not an Alertissimo broker-quorum
result. No `AGN`, `SNII` or `KN candidate` alias is inferred, and no ontology,
score normalization, taxonomy or consensus policy is introduced.

## Primary-source audit

The official Fink object API source was re-fetched and inspected at
[`a10923b0626aa7b73ef41e684e198c96713f2dd3`](https://github.com/astrolabsoftware/fink-object-api/tree/a10923b0626aa7b73ef41e684e198c96713f2dd3).
The working source files matched that upstream revision during preparation.

- [`assets/fink_types.csv`](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/assets/fink_types.csv)
  supplies the provider's native labels; `apps/routes/v1/ztf/classes/api.py`
  exposes that list as the Fink-classifier category.
- [`apps/routes/v1/ztf/latests/utils.py`](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/routes/v1/ztf/latests/utils.py)
  distinguishes ordinary index scans from rewritten aliases and grouped routes.
- [`apps/utils/decoding.py`](https://github.com/astrolabsoftware/fink-object-api/blob/a10923b0626aa7b73ef41e684e198c96713f2dd3/apps/utils/decoding.py)
  computes the returned `v:classification` when the full output is requested.

| Physical route | Inspected behavior | Semantic admission in C7a |
| --- | --- | --- |
| Eight ordinary labels above | `ztf.class`, unchanged label prefix plus JD bounds, ungrouped alert output | Admitted literal equality |
| `(SIMBAD) ...` | Prefix is removed before the class-index lookup | Retains its existing deferral |
| `(TNS) ...` | Separate `ztf.tns` table and prefix handling | Retains its existing deferral |
| `SLSN candidate` | Separate `ztf.slsn` table and grouped alerts | Retains its existing deferral |
| `(CTA) Blazar low state` / `high state` | Separate low/high-state tables and grouped alerts | Retain their existing deferral |

The official [class-search guide](https://doc.ztf.fink-broker.org/services/search/classsearch/)
documents the alert-based class endpoint and its cap; the
[classification guide](https://doc.ztf.fink-broker.org/broker/classification/)
distinguishes provider classifier tags from catalogue-derived classes. Merely
appearing in the physical API's accepted list is not sufficient semantic proof
for all of those different routes.

## Preserved scientific contract

Only the declared literal domain changes. Existing IR, compiler, planner,
binder, execution, response mappings and provider recipe structure are unchanged.
`exact: false` retains normalized checking of the returned class; native index
membership alone does not manufacture a current class assertion. Missing or
different returned labels do not qualify candidates.

`within` selects class-indexed alerts by observation time, not an object's current
classification, first detection, processing epoch or classifier issue time.
Repeated alerts consolidate into the same exact ZTF object identity while
retaining their records. Downstream retrieval receives only survivor IDs and
keeps the returned whole history, including old differently classified points.

The existing raw-alert cap fails before local pruning, including when all capped
rows would be rejected. There is no inferred pagination, history completeness or
global object `latest` contract. First/last, Rubin discovery, OR/NOT without an
eligible native class condition, special aliases/routes and arbitrary criteria
retain their existing guards. Continuation pins the original clock and execution
prefix rather than refilling or rerunning class discovery.

## Verification and remaining C7 scope

The added tests use explicitly synthetic relabelled copies of an immutable alert
template. They are not new deployed captures for the six labels. Native-filtered
and deliberately overbroad replay responses select the same objects after local
class/time checking on the controlled population. Tests also cover qualified and
scoped conditions, repeated-object multiplicity, full downstream history,
missing/different assertions, saturation before pruning, serialization,
continuation and unsupported coarse aliases/special routes.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_fink_semantic_search.py \
  tests/test_orchestration_fink_time.py \
  tests/test_fink_ztf_authoritative_payloads.py \
  tests/test_fink_registry_architecture.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_within_modes.py \
  tests/test_api_continuation.py \
  tests/test_recipe_registry.py \
  tests/test_discovery_integration_acceptance.py \
  tests/test_orchestration_predicate_evidence.py \
  2>&1 | tee /tmp/alertissimo-fink-native-labels-tests.log
```

Preparation passed 354 offline cases across the modules above. No live alert or
object retrieval was run during preparation. Deployment acceptance remains a
separate local step; source inspection and synthetic replay are not live proof.
This provider-declaration slice needs no extra intermediate CI checkpoint after
its focused checks. Final integration CI/live handoff and #329's draft status
remain unchanged.

Lasair's native classification joins still require an explicit audited SQL
contract and a separate implementation slice. They are not enabled by this
change. Other C7 provider/survey work and C4's remaining guards stay explicit.
