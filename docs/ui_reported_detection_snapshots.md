# Reported detection snapshots

The live result card previously displayed every distinct provider count in its
summary history. Fink ZTF alert rows map `i:ndethist` to `detection_count` and
`i:jdendhist` to `time.last_mjd`. Captured data confirms that these counts evolve
with each alert; they are not independent current object totals.

The UI now projects the count at the greatest finite `time.last_mjd` separately
for each qualified summary type and object identity. It does not choose the
largest count, rely on response ordering, sum snapshots, or combine brokers.
Conflicting counts at the newest known epoch and counts with unknown epochs stay
visible. Missing counts stay absent; a reported zero remains zero.

All normalized records and the complete Provider summaries table are preserved.
Filtering does not rewrite a provider's reported object count or turn it into a
count of loaded/retained detection points. This patch changes only the compact
Reported detections metric; Latest mag and Leading class are outside its scope.

Branch `fix/ui-reported-detection-snapshots` is independent of UI branch 02 and
starts from main `1d715ac`. Merge branch 02 first, then rebase this fix on current
main. The changes are in separate areas of the shared files.

Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_app_search_portfolios.py \
  tests/test_app_plot_semantic_records.py \
  tests/test_ui_fixtures.py

PYTHONPATH=. python -m streamlit run alertissimo/app_search.py
```

Repeat the live query and filter that exposed the history list. The card should
show the newest dated count for each provider; open the Portfolio to confirm the
historical summaries remain available. Offline regressions check response-order
independence, decreasing counts, equal-time conflicts, unknown epochs, zero, and
preservation of the full summary table. Tests and live calls were not run while
preparing this fix.
