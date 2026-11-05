# Measurement display and candidate selection

Branch `fix/ui-02b-photometry-filter` starts from main `5938bc3` (PR #290).

The DSL `filter` selects candidate Portfolios. For a single detection selector,
a candidate survives when at least one matching detection satisfies the predicate.
Its other detection records remain intact, including low-scoring records and
records with missing quality values. A later retrieval can add measurements.

| Reference | Evidence selected |
| --- | --- |
| `measurement@ztf:fink.quality.real_bogus` | Fink detections from ZTF |
| `measurement@ztf:lasair.quality.real_bogus` | Lasair detections from ZTF |
| `measurement@lasair:fink.quality.real_bogus` | An incorrect qualifier for these ZTF detections; Lasair is a broker, not their survey |

A local filter can name a qualifier for which no records exist. It does not
retrieve matching records or prove provider support. A successfully executed
filter with no matching evidence can therefore return no objects. Earlier
investigation stages remain visible above that result; they are earlier snapshots.

## Display controls

Open an object and choose **Detections & light curve**. **Display measurements**
offers bands, brokers, and an optional inclusive real/bogus threshold. Quality
filtering starts disabled. Enabling it defaults to `0.999` and excludes missing
scores. A separate checkbox explicitly includes missing scores. Missing values
are not interpreted as zero; zero is an ordinary numeric score.

These controls select the same measurements for the chart, table, shown-point
count, provider breakdown, and detection inspector. Empty selections show an
empty table and explanatory message. Original record IDs and provenance are
preserved. Real/bogus hover values use six decimal places; full precision remains
available in the inspector. Values are the normalized broker values, without
cross-broker recalibration.

The object header and result cards report loaded points. Summary, Semantic Records,
and Provenance continue to show the full evidence. Changing display controls makes
no provider calls, modifies no Portfolio, and does not change continuation input.

## Collect both light curves before candidate filtering

Start a fresh investigation with:

```text
objects from ztf via lasair
inside (124.87996115142856, -6.0205001, 5arcsec)
with lightcurve via fink
with lightcurve via lasair
```

Then submit this in its continuation editor:

```text
filter measurement@ztf:fink.quality.real_bogus >= 0.999
```

This keeps objects with qualifying Fink evidence. To view only their qualifying
Fink measurements, select broker **fink**, enable the display threshold, and keep
the missing-score checkbox off. To inspect Lasair evidence instead, select broker
**lasair**; blank scores are excluded under the same default policy.

## Rejected requests

Validation and execution errors persist across widget reruns. When a request is
rejected, its prior successful result remains available with an explicit warning
that the latest request was not applied. It does not receive a new success banner.
Successful resubmission clears the error and invalidates old descendant results
and error messages, while preserving editor drafts and submit nonces.

## Local verification

No tests, apps, or live requests were run while preparing this branch. Python AST
and Git whitespace checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_app_search_portfolios.py \
  tests/test_app_plot_semantic_records.py \
  tests/test_ui_fixtures.py \
  tests/test_api_continuation.py

PYTHONPATH=. python -m streamlit run alertissimo/app_search.py
```

Load both light curves as above. Check that enabling `0.999` hides scores below
the threshold and blanks in both plot and table. Check exact boundary inclusion,
broker and band controls, missing-score opt-in, and empty selections. The shown
count and inspector options must follow the same selection. The full Semantic
Records view must remain unchanged. Inspecting overlapping provider records must
retain each record's own provenance.

Submit a deliberately malformed continuation such as `filter (`. Its error and
previous-result warning must persist when other widgets rerun the page. A valid
resubmission must clear that status. These checks need no additional live scenario
script beyond obtaining the investigation's initial data.
