# UI state and remaining work

The current UI uses Streamlit and the existing DSL/public API. Provider recipes,
binding, execution and normalization remain backend responsibilities; shared
presentation extracts scientific values from canonical Portfolios.

## Current surfaces

| Entry point | Current behavior |
| --- | --- |
| `alertissimo/app.py` | Launches `app_search.main` |
| `alertissimo/app_search.py` | ID/basic cone forms search saved normalized fixtures; DSL mode validates and executes live workflows, shows candidate cards and opens one Portfolio |
| `alertissimo/app_dsl.py` | Validates/plans complete programs offline using explicit `continue_from=None` |
| `alertissimo/app_plot.py` | Object evidence, photometry/display controls, classifications, contextual records, products and provenance |
| `alertissimo/ui/app.py`, `ui/views/multi_portfolio.py` | Serialized Portfolio upload viewers |

The investigation page already passes the editor's visible parent result to both
`validate_dsl` and `execute_dsl`. Explicit `None` starts fresh work; an explicit
result continues it. Calls omitting the argument retain the process-local
compatibility context and shared lock. No hosted session/database service is needed.
Incomplete supplementary execution still prevents incremental replay.

Rejected submissions retain the previous successful view and persistent failure
feedback. Successful parent replacement clears stale descendant results/selections;
editor drafts and submission markers prevent cached events from replaying requests.
Runtime optional-call warnings remain visible. Frozen examples are demonstrations,
not prior executions eligible for replay or evidence of current provider uptime.

Candidate `filter` selects objects and retains their scientific records. Band,
broker and optional real/bogus display controls restrict the same chart/table/count/
inspector rows without changing the Portfolio, making calls or changing continuation.
Missing quality is excluded under an enabled threshold unless explicitly included;
zero is a numeric value. Reported detection counts remain provider summary evidence,
separate from loaded points. Compact counts use the greatest finite summary
last-MJD per qualified summary/object; equal-time conflicts and unknown epochs
stay visible, without summing brokers or choosing the largest count.
Classification display follows the
[comparison contract](classification_comparison_view.md).

## Remaining beta work

[Implementation item 8](next_functional_work.md#8-deployable-ui) owns the remaining
live ID/cone, installation, asset and interaction work. Investigation startup still
imports `scripts.build_ui_fixtures`; a clean wheel lacks that checkout dependency
and the editor HTML asset. A source-checkout launch does not prove installed UI
readiness. Keep demos/uploads explicit and use capability validation for new controls.

Retain Streamlit, the public facade and shared presentation. Scientific values must
stay traceable to records and provenance; conflicts and unknowns stay visible.
Magnitude axes remain inverted; flux and magnitude, ordinary/forced values and
limits remain distinct. Keep stable band colors and attributable uncertainty.
AppTest does not execute editor JavaScript, so browser
interaction and clean installed startup need their own verification.
