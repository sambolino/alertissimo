# C1 — Multi-broker classification requirements

Branch: `feat/classification-multi-broker-requirements`.
Base: `9b19e26` (#331) on `integration/discovery-completion`.
Target: integration; keep main-target #329 draft.

R2's manual DSL check [41139060499](https://github.com/sambolino/alertissimo/actions/runs/41139060499)
and registry check [41139199475](https://github.com/sambolino/alertissimo/actions/runs/41139199475)
both succeeded on `9b19e2609307315bd0b40577ffddc265d7b53924`.
Those runs validate the base, not this change. No CI was started for C1.

## Language and execution

```text
objects ZTF21abfmbix from ztf via alerce
with classification via alerce, fink
```

This retrieves both brokers' available classification material through existing
GetClassificationSteps. It does not require both brokers to supply a record for
the candidate, elect a winner, equate labels, average scores, or impose quorum.
Provider-call failures retain their existing execution failure behavior.

The authored list remains one surface clause, so capability diagnostics retain
its original clause index. Its broker-bound requirements use the existing
capability, retrieval, planning and execution paths. Existing IR needs no new
fields or operations. Single-broker `via` keeps its original string field; the
surface's new `brokers` tuple is used only for an explicit list. Exact duplicate
requirements emit no additional retrieval Step, including compatible repeated
requirements in continuation. Previous workflow prefixes remain unchanged.

Inline predicates are also supported:

```text
objects ZTF21abfmbix from ztf via alerce
with classification via alerce, fink where best.class = "SN candidate" and assessment.sn_vs_all.probability >= 0.8
```

Unqualified classification references inherit one listed broker at a time. The
whole condition is scoped to that broker, and the alternatives are joined by OR
using existing predicate nodes. At least one listed broker must supply a witness
for the whole condition. Class/score cannot be combined across brokers or records.
All survivor measurements and other assertions remain available.

This example uses a mapped Fink label and named assessment, not a universal
class-probability pair. ALeRCE's probabilities normally use named assessment
leaves and may not provide these same fields. Missing material cannot satisfy a
comparison. Fully qualified references retain their explicit qualifiers, allowing
deliberate cross-broker conditions. To require a broker quorum, use Confirm.

The list only expands classification retrieval. Candidate-source and Match broker
qualifiers remain singular, while Confirm retains its existing broker list.
Other product lists fail explicitly. Repeated broker names are rejected, and an
unavailable/ambiguous member is not silently dropped from the request. A `from`
model applies to every listed broker; it is not a model-alias table.

## Remaining scope

C1 does not activate new discovery filters or solve C4's material scheduling.
Plain classification retrieval after supported discovery can use the list.
Initial discovery conditions requiring evidence from later brokers still defer
before calls, and the existing discovery restriction on a general `where` after
`with` remains. Named lookup selection and continuation can evaluate conditions
after retrieval using existing FilterSteps. Confirm proposition attachment stays
C5 work; a broker list does not change which clause supplies its proposition.

Provider contracts remain those of the base branch. In particular, generic
classification retrieval ambiguities on Fink LSST and Lasair still need C2 review;
listing brokers does not establish support for a deferred single-broker route.

## Local verification

Preparation used source inspection, static Python AST parsing, runbook path and
whitespace checks, and Git bundle verification. No project imports, tests, builds,
applications or live broker calls ran here.

The new offline module covers formal syntax and surface/IR serialization,
single-broker compatibility, scalar/list equivalence, capability attribution,
exact deduplication, whole-condition scoping, retrieval in either broker order,
empty responses without a quorum requirement, immutable continuation and
pre-transport rejection of unsupported members. The existing DSL CI glob includes
the module automatically.

Run locally:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_dsl_surface.py \
  tests/test_dsl_lowering.py \
  tests/test_dsl_fragments.py \
  tests/test_dsl_capability_validation.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_alerce_classification.py \
  tests/test_dsl_confirm.py \
  tests/test_dsl_predicate_preservation.py \
  tests/test_orchestration_predicate_evidence.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-classification-multi-broker-tests.log
```

After success, push and squash into integration without another CI checkpoint.
Continue to C2 retrieval-contract inspection. Run intermediate CI if that work
changes shared retrieval admission or composition, and retain final checks on
the actual main-target head. No additional live scenario is needed for C1 syntax
and lowering alone.
