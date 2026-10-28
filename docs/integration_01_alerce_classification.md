# Correct ALeRCE classification retrieval and static admission

The two reported ZTF classification programs previously either admitted competing
fresh endpoints or passed an unsupported `classifier` keyword to the Python client.
Fresh ALeRCE classification retrieval now uses `query_probabilities`; named
classifiers select normalized records locally. Unconstrained retrieval keeps all
returned models and versions. A missing requested model produces an empty
classification selection while retaining the candidate's other material.

This is PR 01 of the [discovery integration plan](discovery_integration_plan.md),
based on main `7dcff34ecc7320afd1fcd97247d60abe1fde6c61`. Only this branch has been
implemented. No new architecture layer, workflow/result model, provider adapter,
recipe vocabulary, or scientific DSL syntax was introduced.

## Contract evidence

The official PyPI `alerce` 2.3.1 wheel was downloaded for source inspection only,
without installation or broker requests. Its SHA-256 and inspected parameters are
recorded in `tests/fixtures/alerce/probabilities_contract.json`. The public method
accepts `oid`, `format`, `survey`, `index`, and `sort`; it accepts no `classifier`
keyword. The ZTF legacy and Rubin multisurvey branches were inspected separately.
Existing captured probability responses establish their different model names,
version types, and class/probability/ranking fields.

The ZTF endpoint declaration now matches that signature. Rubin already declared
it correctly. Both surveys retain rank under `assessment.{output}.rank`, alongside
the original label, probability, and producer name/version. Rank does not create
a selected `best` class; no latest-version or cross-model winner is inferred.

## Existing execution boundaries

- The shared classification resolver admits local selection when the targeted
  recipe maps dynamic producer identity. A physical parameter alone does not
  establish a request translation.
- The planner still prefers uniquely proven required discovery material through
  the existing material/reuse proof. An unproven owner instead needs a fresh,
  target-bound probabilities call. Equally feasible alternatives remain ambiguous.
- Normalization applies the classifier to the materialized Step view, scoped by
  record-linked execution broker and survey. The same selection is used during
  staged execution, workflow normalization, and finalization. Physical execution
  groups and preceding Step snapshots remain intact, including excluded models.
  Other brokers/surveys and non-classification material are preserved. Record IDs,
  model versions, and execution provenance are retained; projected snapshots and
  remapped Portfolio edges receive distinct internal IDs when their content changes.
- Public `validate_dsl` now also invokes the existing offline `plan_workflow`.
  Deterministic planning failures use the existing validation error channel with
  code `planning_error`. Static capability feasibility alone does not assert that
  execution can choose an unambiguous plan. Validation makes no provider calls.

## Validation handoff

Python AST, YAML/JSON parsing, whitespace, and bundle integrity were checked during
preparation. Tests, package builds, apps, and live broker calls were not run here.
Run the focused contracts locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_alerce_classification.py \
  tests/test_alerce_ztf_endpoint_contracts.py \
  tests/test_alerce_classification_mappings.py \
  tests/test_alerce_ztf_authoritative_payloads.py \
  tests/test_alerce_lsst_authoritative_payloads.py \
  tests/test_alerce_registry_architecture.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_classification_material.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_public_api.py \
  tests/test_api_continuation.py
```

The new public regressions replay recorded ZTF/Rubin rows through the real registry
and Python transport with an offline client implementing the inspected strict
signature. They cover both reported ZTF examples, missing models, preservation of
all versions/ranks, explicit continuation, and static rejection of a synthetic
ambiguous or unbound recipe. Controlled lookup identity substitution in the two
reported examples is documented in the test; it is not a new live capture.

The existing DSL and Semantic registry CI jobs cover the touched runtime files,
provider declarations, and relevant regressions. Runtime files/resources already
fall under the package's existing module/YAML inclusion rules.

After offline tests pass, run the two reported programs live:

```bash
PYTHONPATH=. python - <<'PY'
from collections import Counter
from alertissimo.api import execute_dsl, validate_dsl

for selector in ("", " from lc_classifier"):
    source = (
        "objects ZTF21abfmbix from ztf via alerce\n"
        f"with classification{selector} via alerce\n"
    )
    validation = validate_dsl(source, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, continue_from=None)
    models = Counter(record.semantic_type for portfolio in result.portfolios
                     for record in portfolio.records
                     if record.semantic_type.startswith("classification@"))
    print(source, "Portfolios:", len(result.portfolios), "Models:", dict(models))
PY
```

An upstream failure is not a passing live result. An absent model legitimately
produces no classification records for that selection; investigate the retained
execution evidence when comparing availability. Aggregate candidate counts,
class/time discovery, provider expansion, and nucleuswatch integration remain in
their later planned branches.
