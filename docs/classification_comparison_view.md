# Classification comparison view

## Stored taxonomy headlines

Headline rows show stored `best.taxon` codes with dictionary names and a local
extension marker, such as `9220 Asteroid (Alertissimo ext.)`. Native labels,
versions (including agreeing-version tuples), alternatives, scope, basis, status,
policy digests and unmapped-label errors remain visible. The shared presentation
extractor owns formatting for typed and serialized Portfolios; it never selects
or remaps evidence. The surface script retains the user's query alias, while the
IR stores resolved integer code sets. Comparisons and Confirm use three-valued
ancestry semantics described in [headline policy](classification_headline_policy.md).

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
the presentation invents no taxonomy or model-version precedence.

Probability and score have distinct columns. In particular, Sherlock reliability
2 remains score 2, and Fink CATS scores are not relabelled as probabilities.

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

The Classifications tab is also available without loaded photometry.

Result cards now summarize distinct reported label text without choosing the
first record as an overall leading class. They show a probability badge only
for a single labeled output with an explicit finite probability in [0, 1]. A
score or one probability selected from multiple assertions never becomes a
card-wide confidence estimate.

Catalogue classifications remain in their crossmatch context. The presentation
reads the stored reviewed headline; it does not derive one, calibrate scores,
average probabilities or introduce a consensus policy.

Generated demo fixtures and Streamlit projection caches use the deterministic
revision of the generator, normalization, declarations and frozen inputs. Stale
or unversioned files rebuild from captures; fresh files are reused.

## Regression evidence

[`test_app_classification_comparison.py`](../tests/test_app_classification_comparison.py)
checks output-local metrics, versions, conflicts, source-linked timing, unchanged
records, stored headlines, card summaries and independent classification-only
views. AppTest coverage does not establish browser JavaScript behavior.
