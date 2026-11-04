# C2b — Lasair classification retrieval contract

Branch: `fix/classification-lasair-contract`.
Base: `d5c762d` on `integration/discovery-completion`, after C2a and the formal
grammar test correction. Target: integration; keep #329 draft.

## Declaration change

Use one context-bearing object response as the declared classification route:

| Survey | Classification endpoint | Binding |
| --- | --- | --- |
| ZTF | `objects` | `objectIds` CSV, including a single ID |
| LSST | `object` | singular `objectId`; existing binder fans out for multiple IDs |

The existing mappings establish Sherlock class, description and reliability on
these responses. ZTF additionally maps TNS type when present. The dedicated
Sherlock response maps class and description, but not that reliability field.
It is a narrower alternative for this classification request, rather than the
complementary object/source evidence that required Fink LSST's composed recipe.

Remove the competing GetClassification recipe declarations for the dedicated
Sherlock endpoints and the redundant singular ZTF alternative. Keep every
endpoint, mapping and other operation's recipe unchanged. This is an authored
retrieval contract, not a general ranking heuristic between arbitrary endpoints.
No new architecture layer, IR node, recipe field, planner branch or ontology field
is introduced. Existing true duplicate-recipe ambiguity remains an error.

The ZTF collection route has an unchanged captured one-object array response.
The LSST route uses the existing registered `lasair_added: true` default; its
context-bearing capture establishes the mapped fields. No classification request
parameter is invented. Capture presence establishes these response contracts,
not historical completeness or an assertion that optional context always exists.

## Scientific material and reuse

Both generic retrieval and `from sherlock` retain the mapped reliability as
`best.score`, without relabelling it as a probability or calibrated confidence.
Producer/channel identity remains `classification@sherlock:lasair`.

On ZTF, `from tns` selects only TNS classification records. A TNS registration
with no `type` supplies no TNS classification; it must not inherit Sherlock's
label or manufacture a type from the TNS prefix. LSST has no mapped TNS
classification contract and continues to reject that producer request.

The selected rich response may also yield measurements, summaries and context.
Candidate filtering preserves the complete surviving Portfolio. Prior workflow
snapshots and execution provenance remain immutable. The ordinary per-call reuse
proof permits an LSST object lookup to satisfy the classification Get without a
new request. A singular ZTF lookup and the declared collection classification
route are different calls and are not treated as interchangeable by guesswork.
Plural ZTF lookups can reuse the same declared collection endpoint when their
existing request/lineage proof matches.

This does not compare label truth, merge scores, pick a model version or select
the latest assertion by endpoint order. Dedicated Sherlock mappings remain
available to existing Crossmatch and explicit endpoint consumers. ZTF crossmatch
route ambiguity is unchanged; this branch resolves classification only.

## Local verification

Preparation used source review, static Python AST/YAML parsing, capture inspection,
whitespace and bundle checks. No project imports, tests, builds, applications or
live broker requests ran here. All frozen capture files and mappings are unchanged.

New offline regressions cover both surveys and target cardinalities, generic and
named producers, class/description/reliability provenance, LSST lookup reuse,
continuation and survivor-record retention, missing TNS type, unsupported
producers and failure without silent endpoint fallback. One separate, explicitly
synthetic TNS payload tests a positive typed-TNS case; no capture is edited to
create it. Existing direct Sherlock normalization/Crossmatch tests remain active.
The new module is included by DSL CI and explicitly by registry CI.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_lasair_classification.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_dsl_enrichment_family.py \
  tests/test_api_continuation.py \
  tests/test_lasair_registry_architecture.py \
  tests/test_lasair_ztf_live_capture.py \
  tests/test_lasair_lsst_live_capture.py \
  2>&1 | tee /tmp/alertissimo-classification-lasair-tests.log
```

After local success, push and squash into integration. No additional intermediate
CI is requested for this declaration-only retrieval change. Keep #329 draft and
retain final validation on the eventual main-target head. Next is C3: inspect
missing classification evidence/mappings, starting with one ANTARES survey.
