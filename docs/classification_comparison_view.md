# C6 — Compare existing classification assertions

Branch: `feat/classification-comparison-view`.
Base: `b666c34` on `integration/discovery-completion`, after C5 (#343).
Keep main-target #329 draft.

## Current extension: stored taxonomy headline comparison

Headline rows show stored `best.taxon` codes with dictionary names and a local
extension marker, such as `9220 Asteroid (Alertissimo ext.)`. Native labels,
versions (including agreeing-version tuples), alternatives, scope, basis, status,
policy digests and unmapped-label errors remain visible. The shared presentation
extractor owns formatting for typed and serialized Portfolios; it never selects
or remaps evidence. The surface script retains the user's query alias, while the
IR stores resolved integer code sets. Comparisons and Confirm use three-valued
ancestry semantics described in [headline policy](classification_headline_policy.md).

The native-only C6 history below predates this extension; its normalization
deferral is superseded by that policy.

## Scientific presentation

The object Portfolio's Classifications tab now shows every reported `best` and
named `assessment` output as a separate presentation row. A label is paired only
with probability/score/rank fields from its own output and original source
record. A scalar named output without a label remains a scalar output; the view
does not infer its class from a nearby label or its name.

The table presents the actual delivery broker, semantic producer, available
producer/model name and version, output path, label, probability, score and rank.
Mapped method, target, description, generic values and other named outputs remain
available. Repeated records, competing versions and conflicting assertions are
retained. Numeric classifier labels remain numeric codes in the source record;
no taxonomy or model-version precedence is invented.

Probability and score have distinct columns. In particular, Sherlock reliability
2 remains score 2, and Fink CATS scores are not relabelled as probabilities. The
old projection could pair the first encountered class with an unrelated
assessment probability, fall back from probability to score, and misparse the
qualified type as a broker name. C6 removes those presentation shortcuts.

Each row retains its original record identity. The record inspector shows all
normalized fields and that record's linked execution provenance. This is a
transient table view over existing records, not another scientific record model.
Canonical Portfolio records, executions and edges are not modified.

## Timing and scope

Associated observation MJD/source IDs come only from measurement records with
the exact same complete physical source reference. No object summary epoch or
other row from the execution is substituted. If that source has several mapped
epochs, the view retains them instead of selecting one as latest.

Mapped assertion MJD/datetime and production MJD are shown separately from the
execution's retrieval completion time. Missing values remain missing; request
start time, adapter version, observation epoch and version-name ordering never
invent classification issue times or model versions.

The Classifications tab is also available without loaded photometry. The old
summary-only layout hid useful classification evidence and described such
Portfolios as summary-only even when they held other material.

Result cards now summarize distinct reported label text without choosing the
first record as an overall leading class. They show a probability badge only
for a single labeled output with an explicit finite probability in [0, 1]. A
score or one probability selected from multiple assertions never becomes a
card-wide confidence estimate. The cached demo projection changes with this
view contract. The fixed extragalactic-transient demo interpretation is removed.

Catalogue classifications remain in their existing crossmatch context. They
are not promoted into candidate classification assertions. No label
harmonization, coarse-family mapping, score calibration, derived best policy,
probability averaging or consensus policy is inserted. The normalization
discussion remains deferred as requested. Compiler, planner, runtime, provider
contracts and ontology are unchanged.

## Verification and handoff

The new comparison tests use frozen ALeRCE, Fink and Lasair payloads alongside
controlled missing/conflicting data. They check output-local class/metric
association, model versions, duplicates, original score scales, exact row-linked
timing, large source IDs, missing provenance, unchanged source records, empty and
catalogue-only views, card summaries, inspector provenance and two independently
keyed classification-only object views through Streamlit AppTest.

The UI workflow explicitly includes the new comparison module. Run the same
offline UI contracts locally:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_app_classification_comparison.py \
  tests/test_app_search_portfolios.py \
  tests/test_app_plot_semantic_records.py \
  tests/test_ui_fixtures.py \
  tests/test_application_portfolio_access.py \
  tests/test_portfolio_lightcurve.py \
  tests/test_portfolio_serialization.py \
  tests/test_dsl_public_api_serialization.py \
  tests/test_target_bound_partition_identity.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-classification-comparison-tests.log
```

Preparation passed 102 offline cases across these modules, including the
Streamlit rendering checks. No live provider request was run.

A local upgrade exposed six failures from old generated UI files, including
pre-rename `detection` records and obsolete classification fields. The fixture
loader now checks a deterministic revision of the generator, normalization code,
registry/ontology and frozen inputs. Unversioned or stale generated files rebuild
from the captures; fresh output is reused. Streamlit's Portfolio and search-row
caches include that same revision. The scientific assertions and captures are
unchanged. The follow-up passed 111 offline checks, including an old-corpus
upgrade regression, input-change checks and cache-key propagation.

After local checks and squash, run the UI workflow on the integration head.
No additional DSL/registry checkpoint is requested for this presentation-only
slice. Final integration checks and live acceptance remain required; #329 stays
draft. C7's audited native discovery bindings and C4's remaining explicit guards
are not completed by this view.
