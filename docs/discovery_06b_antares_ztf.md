# ANTARES ZTF numeric coordinate discovery

Branch `feat/discovery-06b-antares-ztf`, based on integration `634b879` / PR #317.
Target `integration/discovery-completion`; squash after focused local checks.

## Activated request

```text
objects from ztf via antares
where summary.position.ra >= 50.847 and summary.position.ra <= 50.849 and summary.position.dec >= 37.467 and summary.position.dec <= 37.469
with lightcurve via antares
```

This is an ordinary rectangular coordinate predicate in degrees. RA wraparound
would require an OR or separate requests; do not reinterpret contradictory RA
bounds as a cone. Existing `inside` cone discovery keeps its own recipe.

The production `search` recipe admits numeric `=`, `<`, `<=`, `>` and `>=` over
the existing RA/Dec summary mappings, including conjunctions and reversed
operands. The whole initial predicate must translate. Bare semantic discovery,
unsupported fields/operators, strings/bools in numeric conditions, and OR/NOT do
not become an unrestricted catalogue request. Classifications and catalogue tags
are not aliases for these conditions.

Each query includes the existence of `properties.ztf_object_id` to select the ZTF
identity in the shared survey index. The optional `identity_field` in the existing
Elasticsearch binding representation must name a mapped summary object identity.
Bindings sharing one physical parameter must share the same identity scope.
The planner also retains a source-qualified identity-existence residual alongside
the requested coordinate predicate, so overbroad returned rows cannot promote
a foreign-survey locus ID into a ZTF candidate ID. An ANTARES locus that also has
another survey identity can still be selected by its actual ZTF identity.

No ontology leaves, response mappings, new architecture layer, IR operation or
provider-specific planner branch is added. Physical query syntax stays in the
provider declarations and existing pure encoders. Rubin semantic discovery remains
separate and unactivated.

## Iterator execution and replay

The existing Python client transport now exhausts one-shot iterators into tuples
before returning an execution result. This covers every page the client yields
and retains a replayable snapshot for staging, independent normalization and
continuation. An exception while fetching a later page fails the owning provider
call before any partial result becomes successful semantic material. Returned
Locus objects retain their existing lazy relationships; this change exhausts the
result iterator, not every lazy attribute of each object.

The normalizer already materializes iterators locally while building records,
but that leaves the original execution payload consumed. Freezing at execution
preserves the raw result for later replay too. Lists, dictionaries, scalars and
other non-iterator return types keep their existing representation. No executor
pagination framework or second copy of ANTARES HTTP pagination is introduced.

Every downstream targetless retrieval binds the discovered and subsequently
filtered ZTF IDs. Measurements for survivors retain their existing normalization.
Continuation replays discovery without contacting the native search function again.

## Temporal and latest follow-up

`within`, `first within`, `last within` and `latest` remain deferred on this
semantic recipe. They are the next ANTARES evidence step, 06c. The existing frozen
ZTF history contains candidates and upper limits, and the client lightcurve omits
some alert records. Consequently, newest/oldest **alert** time and total-alert
count cannot simply be mapped to detection extrema and count. This branch does
not make those substitutions. See the unchanged frozen
[history audit](../tests/fixtures/antares/ztf/README.md).

The follow-up must establish full detection evidence and its completeness before
admitting temporal membership or global ranking. Classification joins and
additional Rubin discovery retain their agreed end-of-series consultation.

## Verified primary contracts

- Repository dependency remains `antares-client==1.14.0` in `setup.py`; no client
  version migration is hidden in this activation.
- [Pinned official 1.14.0 search](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/944197ad2bdae5b46641ddf5f76711e1e327e6f0/antares_client/search.py)
  takes one query dictionary, uses the shared index and looks up ZTF identity at
  `properties.ztf_object_id`.
- [Pinned pagination helper](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/944197ad2bdae5b46641ddf5f76711e1e327e6f0/antares_client/_api/api.py)
  follows `links.next` until absent and raises on HTTP errors. There is no supplied
  top-N argument or manual single-page parameter in this recipe.
- [Official query examples](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/9c49e1eecdb5e3b8e2d214133494fcb806a1bc5a/docs/source/tutorial/searching.rst)
  show numeric ranges on top-level `ra` and `dec` under compound queries.
- [Elasticsearch exists semantics](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-exists-query)
  and [bool.filter semantics](https://www.elastic.co/docs/reference/query-languages/query-dsl/query-dsl-bool-query)
  establish the structured identity-scoped conjunction. The field's scientific
  identity still comes from the ANTARES contract and existing response mapping.

This describes the provider's indexed population and client pagination, not an
atomic snapshot across an evolving catalogue. No deployed server or live broker
request was probed during implementation.

## Local handoff

No project imports, tests, builds, apps or live requests ran here. Static AST,
YAML, whitespace and bundle verification accompany the branch.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_antares_semantic_search.py \
  tests/test_orchestration_elasticsearch_bindings.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_orchestration_one_shot_execution.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_antares_registry_architecture.py \
  tests/test_endpoint_execution.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-discovery-06b-tests.log
```

The native-client fixture exercises two synthetic iterator pages, an unchanged
frozen listing row, empty results, later-page failure, an overbroad response,
identity scope, survivor-only retrieval and replay without new search calls. It
does not claim to exercise real HTTP links; their traversal is established by
the pinned client source. Unsupported temporal/selection forms reject before
the fake native client is called. Existing untranslated-ZTF expectations now
check the missing required query through the new provider test.

DSL CI now includes this provider module explicitly. This branch changes the
shared Python transport and query residual, so run one intermediate manual DSL
checkpoint after its integration squash. The registry checkpoint can wait until
the temporal/material additions, since no ontology or response mapping changed.
