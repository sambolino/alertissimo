# C2a — Fink LSST classification retrieval contract

Branch: `fix/classification-fink-lsst-contract`.
Base: `bed9c8c` (#332), after the user-confirmed C1 merge.
Target: `integration/discovery-completion`; keep main-target #329 draft.

## Result

Fink LSST's `objects` and `sources` classification routes are complementary.
The first maps the object main label and crossmatch assessment; the second maps
source-associated CATS and other named assessments. Previously they were two
alternative classification recipes, so generic retrieval was ambiguous even
though both used the fixed producer `fink`.

Declare one GetClassification recipe with two required calls: objects, then
sources. Existing recipe expansion, planning, binding, execution and Portfolio
normalization already support this composition. Extend the existing classification
admission check to inspect every call, rather than rejecting all multi-call
recipes. Each call must be required, bind target IDs directly from the Step, and
map classification material. Dependent/encoded target inputs, optional calls and
calls without classification mappings are not admitted. A requested classifier
needs its own fixed/dynamic producer proof on every call, using the existing
server-selector or mapped local-selection rules.

No new architecture layer, IR operation, recipe schema field, endpoint filter,
ontology field or mapping is introduced. Existing provider alternatives remain
ambiguous unless their declarations establish a unique recipe. In particular,
this does not choose Lasair's classification routes; that is the next C2 branch.

## DSL and evidence

```text
object 170587117485817955 from lsst via fink
with classification via fink
```

`from fink` is also supported; CATS is a named assessment on the Fink record,
not a newly invented `cats` producer. Object main labels and source assessment
rows remain separate records with their own execution/payload-row provenance.
Scores are not relabelled as probabilities or interpreted as confidence in the
object main label. No row is chosen as a universal best/version/current result.

The existing object lookup response can satisfy the recipe's object call through
per-call reuse. That reuse does not eliminate the required sources call. An empty
sources response supplies no source assessments; a failed required request fails
execution rather than being reported as successful partial classification.
Bare material retrieval does not require a candidate to have every field.

Fetching source assessments may also materialize measurements/lightcurve records
because they share the response. They remain available to the candidate. The
recipe does not claim a complete historical classification population or turn
this frozen capture into live coverage evidence.

Capability diagnostics expose both required endpoints, while recipe selection
continues to use its primary endpoint as the existing candidate key. Fresh
validation, execution, serialization and continuation use the same contract.

## Local checks

Preparation used source inspection, static AST/YAML parsing, fixture inspection,
whitespace and bundle verification. No project imports, tests, builds, applications
or live provider calls ran here. Frozen fixture bytes and mappings are unchanged.

The new regression module uses the existing Fink LSST capture: one object row and
16 source rows. It checks direct and plural binding, both qualified/unqualified
requests, label/score provenance, retained measurements, object reuse without
dropping sources, immutable continuation, required-call failure, empty evidence,
secondary-call admission and duplicate-recipe ambiguity. It is included in both
DSL and registry CI.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_fink_lsst_classification.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_dsl_multi_broker_classification.py \
  tests/test_dsl_alerce_classification.py \
  tests/test_dsl_enrichment_family.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_orchestration_normalization_reuse.py \
  tests/test_api_continuation.py \
  tests/test_fink_lsst_authoritative_payloads.py \
  tests/test_fink_registry_architecture.py \
  tests/test_recipe_registry.py \
  2>&1 | tee /tmp/alertissimo-classification-fink-lsst-tests.log
```

After local success, push and squash into integration. This changes shared
classification admission, so run one DSL/registry checkpoint on the merged SHA:

```bash
gh workflow run dsl.yml --ref integration/discovery-completion
gh workflow run semantic-registry.yml --ref integration/discovery-completion
```

Keep #329 draft. No new live acceptance is claimed by this offline repair; actual
Fink LSST interoperability can be checked in the later provider live acceptance
pass. Next, inspect Lasair ZTF/LSST classification alternatives separately.
