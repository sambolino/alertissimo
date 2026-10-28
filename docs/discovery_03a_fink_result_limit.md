# Reject saturated Fink JSON responses before discovery activation

Fink ZTF `latests` returns at most `n` alerts. Previously a response containing
exactly `n` rows became an ordinary successful execution, without detecting that
more rows might exist. The existing `RegistryEndpointExecutor` now raises
`EndpointPaginationError` when a declared JSON array ceiling is reached or
exceeded. A full response is conservatively unproven, even if its true total
happens to equal the ceiling. Distinct object counts cannot detect saturation:
several alerts can belong to one object.

This is **03a** of the discovery integration plan, based on merged PR #295,
main `d91106e`. PR 03 is split so the physical safeguard can be reviewed before
activating scientific discovery. No new architecture layer, result type, DSL
keyword, or orchestration policy is introduced. The class/time recipe follows
in 03b after this branch is merged.

## Change and limits

- The existing physical `n` parameter on Fink ZTF `latests` gains
  `role: result_limit`; its existing output selector gains `role: output_format`.
  GET, parameter defaults, headers, mappings, and payload partitioning stay as
  declared. No semantic-search recipe is added in this branch.
- The executor reads the ceiling after defaults and fixed values are applied.
  Invalid ceilings and ambiguous combinations with conventional page pagination
  fail before transport. Positive integer strings retain direct REST usage.
- A JSON result with `len(payload) >= n` fails explicitly with endpoint identity,
  observed count, ceiling, and advice to narrow the query. It never becomes a
  successful `ExecutionResult`. No cursor, retry, or time subdivision is guessed.
- Unsaturated arrays, including empty arrays, pass through unchanged with their
  existing provenance. A declared JSON array endpoint returning an object or
  opaque bytes fails because its row count cannot be verified.
- Explicit CSV, Parquet, and VOTable exports retain one-response raw-byte
  behavior. They carry **no row-count or completeness guarantee**. This guard is
  for JSON arrays, not a binary-export parser. Other endpoints remain opt-in.

The guard detects visible saturation only. An unsaturated result does **not**
prove completeness when the provider groups or filters after its internal cap.
Semantic admission in 03b must restrict itself to verified populations and keep
these special cases deferred. It must also keep physical `n` distinct from global
scientific `latest N` selection. Automated complete retrieval remains future work
unless the window/cursor boundary contract can be established.

## Audited upstream contracts

Read-only source inspection on 28 October 2026 used Fink's official repositories;
no upstream packages were installed or executed and no broker was queried.

| Contract | Evidence | Consequence for 03b |
| --- | --- | --- |
| ZTF `latests` supports GET query parameters and POST JSON | `apps/routes/v1/ztf/latests/api.py` | Existing GET needs no transport change |
| Ordinary classes scan `ztf.class` by class and observation JD, returning alerts | `ztf/latests/utils.py`; broker `bin/ztf/archive_index.py` | Search means objects having matching alert evidence in the requested observation window; it does not establish an object's latest current class |
| ZTF class index and returned `v:classification` use Fink's classification function | Broker `archive_index.py`; API `apps/utils/decoding.py` | Preserve returned class material; indexing versus current decoder/model versions still needs care |
| `n` limits the scan before trend filtering; SLSN and CTA routes group alerts by object | `ztf/latests/utils.py`; `apps/utils/decoding.py` | A short response is insufficient proof for these special routes; do not admit them as ordinary class equality |
| TNS and SIMBAD class aliases select external catalogue tables/labels | `ztf/latests/utils.py` | Do not equate every physical class alias with `classification.best.class` |
| Rubin uses required `tag`, with per-filter API support checks | `apps/routes/v1/lsst/tags/{api,utils}.py` | Tag membership is not arbitrary classification equality; equivalent class discovery remains deferred |
| Rubin tag date conversion and observing timestamps require an independent scale audit | `lsst/tags/utils.py` and existing TAI source mappings | Do not inherit ZTF UTC bindings |

Pinned sources:

- [Fink object API `a10923b`](https://github.com/astrolabsoftware/fink-object-api/tree/a10923b0626aa7b73ef41e684e198c96713f2dd3).
- [Fink broker `d368cb1`](https://github.com/astrolabsoftware/fink-broker/blob/d368cb1526c89fcd3c62bf7c4a9627e3f117f845/bin/ztf/archive_index.py).
- [Official class-search guide](https://doc.ztf.fink-broker.org/services/search/classsearch/).

The existing immutable `tests/fixtures/fink/ztf/latests.json` capture contains ten
alerts for seven objects. It is replayed unchanged below a larger physical cap to
verify identity preservation, then replayed at its original cap to verify refusal
to claim exhaustion. This is recorded upstream data, not a new live capture.

## Local verification

No tests, builds, apps, or live scenarios were run here. Python AST, YAML syntax,
Git whitespace, and bundle verification were checked. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_endpoint_pagination.py \
  tests/test_endpoint_execution.py \
  tests/test_execution_policy.py \
  tests/test_fink_ztf_authoritative_payloads.py \
  tests/test_fink_registry_architecture.py \
  tests/test_orchestration_search_recipes.py \
  tests/test_dsl_candidate_recipes.py
```

The focused regressions cover exact/exceeded caps, duplicate object rows, default
and explicit limits, empty results, invalid limits before transport, wrong JSON
shapes, raw exports, non-opted-in endpoints, and recorded candidate/detection
identity. Existing conventional pagination tests remain in the same module. Both
DSL and semantic-registry CI include that module; executor-only changes now also
trigger DSL CI. No live run is required for this safeguard-only branch.
