# Exhaust declared Lasair offset queries

Lasair query results use `limit` and `offset`, without a continuation wrapper.
The existing executor previously returned one response for these endpoints. It
now exhausts opt-in JSON-array offset queries as one logical execution when the
caller has not explicitly selected an offset. A short page proves the end only
under the declared page contract; an exact-size final page needs an empty probe.

This is **05a**, based on merged ALeRCE PR #302, main `0ab4fca`. PR 05 is split
into this physical paging prerequisite and the subsequent scientific SQL
translation. No semantic-search recipe is activated here. No new architecture
layer, workflow/result model, dependency, or execution-policy file is introduced.

## Physical contract and ownership

Both existing Lasair query declarations mark their `limit` and `offset` parameters
with `role: pagination`. Defaults remain `limit=1000`, `offset=0`. The executor
recognizes the conventional pair, just as it already recognizes `page/page_size`.
Methods, form encoding, headers, `selected`, `tables`, `conditions`, and mappings
retain their existing declarations.

- Without a caller-supplied offset, calls advance by the requested page size.
  Payload rows are combined unchanged; normalization still owns object identity.
- An explicit or transport-fixed offset, **including zero**, selects one physical response. Existing
  ZTF cone supplements already supply `offset=0` and `limit=100`; they remain one
  call even if that response is full. The target-ID condition encoder is untouched.
- Reaching the existing `max_auto_pages` policy raises
  `ExecutionPolicyLimitError`; it never returns an apparently successful partial
  result. An exact multiple at the policy boundary remains unproven and fails.
- Non-array automatic responses (including provider error objects), oversized
  pages, repeated page content, ambiguous modes, and invalid automatic controls
  fail explicitly. No guessed query rewriting or retry is added.
- Original query values and resolved credentials are forwarded to every call.
  Initial parameters, transport metadata, redacted headers, and summed raw byte
  sizes remain in the existing single-execution provenance, as for page pagination.
  There is no new per-page ledger or claim of database snapshot isolation.

The source audit found **account-dependent limit clamping**: a large requested page
can return fewer rows because the server lowered the limit, rather than because
the result is exhausted. `limit.auto_page_size_max=1000` records the inspected
universally safe automatic size. Larger automatic requests fail before transport;
they are not silently reduced or mistaken for complete populations. This is an
automatic-paging safeguard, not a false absolute API maximum. Explicit offset
calls retain the physical API's own handling of larger or otherwise bounded calls.

Stable ordering and a consistent population remain query obligations. Paging alone
does not establish those properties, nor does it make an arbitrary projection
sufficient scientific evidence. Queries projecting identical rows across pages
can fail the repeated-page guard; include distinguishing identity material or
select an explicit bounded offset. The following discovery branch must author a
stable order, verified selected fields, safe predicate translations, and its exact
population. Global `latest N` is not implemented by the physical `limit`.

## Source audit

Read-only source inspection on 29 October 2026 used
[`lsst-uk/lasair4` `2b940d4`](https://github.com/lsst-uk/lasair4/tree/2b940d41c456545164c587e0f053e6312c2d105a):

- `webserver/lasairapi/serializers.py`, `QuerySerializer`: integer limit/offset,
  account-dependent caps of 1000/10000/1000000, default 1000 and zero offset,
  native `LIMIT ... OFFSET ...`, array success and object-shaped errors.
- `webserver/lasair/query_builder.py`: selected/tables/conditions split; ordering
  can appear in conditions; physical LIMIT/OFFSET must be separate parameters.
- The [official client contract](https://github.com/lsst-uk/lasair_api) documents
  `query(selected, tables, conditions, limit=1000, offset=0)` returning row dictionaries.

The existing ZTF and Rubin captures confirm query-array shapes and the declared
input names. They do not constitute a new live multi-page acceptance run. This
source snapshot is not a claim that both deployed services are byte-identical;
deployed behavior and provider availability remain live-acceptance questions.

## Local verification

No tests, builds, apps, or broker calls were run here. Python AST, YAML syntax,
Git whitespace, and bundle checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_offset_pagination.py \
  tests/test_orchestration_endpoint_pagination.py \
  tests/test_execution_policy.py \
  tests/test_endpoint_execution.py \
  tests/test_lasair_registry_architecture.py \
  tests/test_orchestration_composite_cone_recipes.py \
  tests/test_orchestration_sql_recipes.py
```

The new regressions use small synthetic pages and unchanged recorded query rows.
They verify exact-size probing, aggregate provenance, original request immutability,
safe automatic sizes, failure before transport for invalid controls, repeated-page
refusal, explicit-offset compatibility, both surveys' identities, and the existing
ZTF cone supplement. The sampled recorded queries contain one row each; splitting
them into a row and empty probe checks mechanics, not a historical population claim.

The existing DSL CI `test_orchestration_*.py` glob includes the new module; its
execution-source path trigger already covers this executor change. The new paging
suite is not duplicated in semantic-registry CI. Existing registry jobs still
exercise provider contracts and page/result-ceiling regressions.

After this branch is merged, **05b** adds bounded semantic SQL translation using
the current predicate, recipe, and binding interfaces. Its discovery call must
omit an explicit offset to activate exhaustive paging. Generic raw SQL lowering,
unverified class equivalences, and generic historical `within` remain deferred
until their own semantic contracts are established.
