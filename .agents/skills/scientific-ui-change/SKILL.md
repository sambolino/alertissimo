---
name: scientific-ui-change
description: Change Alertissimo scientific UI, photometry charts, classification comparison, record inspection or frozen fixtures while keeping canonical evidence and shared presentation authoritative.
---

Read root `AGENTS.md` and `ARCHITECTURE.md`. Identify whether the affected view
uses live execution, a serialized Portfolio or captured demo evidence.

1. Consume canonical records and shared presentation extraction. Use
   `data_layer/presentation/portfolio_lightcurve.py` for photometry; do not write
   another field-name parser in a display adapter.
2. Preserve quantity, ordinary/forced kind, limits, missing uncertainty, negative
   flux, zero coordinates, record identity and linked provenance. Keep flux and
   magnitude axes separate. Do not let limits become measured brightest/latest.
3. Keep classification labels paired with metrics from their own assertions.
   Preserve conflicts, scores and versions; do not introduce a hidden winner.
4. Keep demo data visibly distinct from live results. Frozen fixtures are saved
   provider responses, not current discovery or proof of service availability.
   Do not show an unrelated image as the candidate's actual image.
5. Express new controls through existing DSL/public API and capability checks.
   Preserve visible-result continuation and prior results on failure. Do not
   invent a session/database/service architecture for deploy-yourself use.
6. Add scientific boundary tests and rendering checks for changed views; verify
   source records stay unchanged. AppTest does not execute editor JavaScript.

Run relevant UI modules, including `test_shared_photometry_projection`,
`test_portfolio_lightcurve`, `test_app_plot_semantic_records`,
`test_app_search_portfolios`, `test_app_classification_comparison` and fixture
checks. Check installed assets/startup when packaging changes. Present tested
behavior, visual limits and exact revision; supply user-run git/gh commands.
