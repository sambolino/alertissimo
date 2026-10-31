# Structured numeric discovery bindings

Branch `feat/discovery-06a-elasticsearch-bindings`, based on integration `cc601ae`
after Fink audit PR #316. Target `integration/discovery-completion`.

ANTARES work is split into 06a (query compilation), then 06b (verified provider
activation and temporal/selection evidence, split further if needed). This first
branch adds no production provider bindings or recipes. Existing ANTARES lookup,
cone and retrieval behavior stays on its current declarations.

Follow-up: [06b](discovery_06b_antares_ztf.md) activates scoped ZTF coordinates;
temporal and latest evidence are separated into 06c. The isolated 06a fixtures
remain independent of the production identity-scope declarations.

## Existing boundaries

The existing `predicate_bindings` format gains one optional representation:

```yaml
predicate_bindings:
  search:
    - path: summary.position.ra
      operator: ">="
      parameter: query
      elasticsearch: {field: ra}
```

This is an illustrative encoder declaration, not a verified production ANTARES
index field. Tests author it only in an isolated provider copy, using an existing
untransformed response mapping. Verifying indexed fields and their scientific
meaning belongs to 06b.

CapabilityGraph compiles the optional field into the existing
`RequestConstraintCapability`. The current recipe compiler requires a declared
dictionary server-filter parameter, a matching endpoint output mapping, no output
transform, an explicit supported operator, and no competing value encoder, SQL
representation or restricted literal domain. Sharing the same parameter across
structured bindings is valid; duplicate semantic path/operator pairs are not.

The existing planner realizes finite numeric `=`, `<`, `<=`, `>` and `>=`:

| IR condition | Client argument `query` |
| --- | --- |
| `summary.position.ra >= 120` | `{"query": {"range": {"ra": {"gte": 120}}}}` |
| `summary.position.ra = 120` | `{"query": {"term": {"ra": 120}}}` |
| `a and b` | One `query` containing `bool.filter` with both conditions |

Reversed operands retain their inverted comparisons. Nested conjunctions and
different fields remain intact. No query-string interpolation, scripts, raw
Elasticsearch syntax in the DSL, search limit, sorting control, or new dependency
is introduced. The new transform module contains only pure dictionary encoders;
it is not an Elasticsearch client or another architecture layer.

Booleans, strings, non-finite numbers, `!=`, OR/NOT, unsupported fields and wrong
qualifiers cannot supply a required structured query. Translation must cover the
whole predicate. A valid subset cannot silently become an unconstrained request.
The existing required-predicate admission check defers missing query assignment.
Successfully translated predicates also remain residual so normalized response
evidence is rechecked. Discovery-call scope and producer/channel checks remain
the same as for existing scalar and SQL bindings.

## Source audit and next activation

Official source was inspected read-only; no installed client or provider service
was executed:

- [Client 1.14.0 search](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/944197ad2bdae5b46641ddf5f76711e1e327e6f0/antares_client/search.py)
  documents a dictionary with exactly one top-level `query` key, delegates result
  pagination, and uses newest-alert observation time ordering.
- [Client main at `9c49e1e`](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/9c49e1eecdb5e3b8e2d214133494fcb806a1bc5a/antares_client/search.py)
  exposes `search(query, limit=10)` with the same query argument. Its
  [API helper](https://gitlab.com/nsf-noirlab/csdc/antares/client/-/blob/9c49e1eecdb5e3b8e2d214133494fcb806a1bc5a/antares_client/_api/v2/utils.py)
  follows `links.next` until exhausted. That limit is a page parameter, not a
  scientific top-N selection.
- [Official search tutorial](https://nsf-noirlab.gitlab.io/csdc/antares/client/tutorial/searching.html)
  shows structured numeric ranges and conjunctions in the query dictionary.

The provider branch must still verify indexed columns, ZTF identity scope,
observation versus detection times, returned summary coverage, client-version
differences and complete population retrieval. An iterator alone is not a proof
of every one of these properties. Rubin discovery and classification joins retain
their end-of-series consultation boundary.

## Local verification

No tests, project imports, builds, apps or live requests ran here. Static AST,
whitespace and Git bundle checks accompany the handoff.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_elasticsearch_bindings.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_lasair_semantic_search.py \
  tests/test_recipe_registry.py \
  2>&1 | tee /tmp/alertissimo-discovery-06a-tests.log
```

The isolated fixture covers loading, planning, binding, numeric operators,
conjunction composition, call scope, qualifiers, invalid declarations, required
query failure and normalized residual rechecking through the public facade.
It explicitly checks that production ZTF/Rubin semantic discovery remains
unactivated in this prerequisite. Existing predicate/SQL regressions protect
other providers. The new test module is covered by DSL CI's orchestration glob.
Keep the agreed local-check/small-squash workflow; a further intermediate CI run
can wait for the ANTARES activation checkpoint.
