# UI overhaul

## Baseline and boundaries

The recipe overhaul and final acceptance correction are merged through main
`79fc666` (PR #288). The user reported four live passes after Fink recovery:
LSST consolidation, cross-provider retrieval, predicate quorum, and incremental
continuation. That closes the previously unavailable Fink LSST acceptance item.

There is already a Streamlit UI. `app_search.py` has frozen ID/cone examples,
live DSL execution, candidate cards, object Portfolio navigation, and a
continuation editor. `app_plot.py` renders normalized records and provenance;
`ui/app.py` and `ui/views/multi_portfolio.py` accept serialized Portfolio uploads.
The README previously advertised only the older DSL compilation prototype.

Keep Streamlit for this sequence. UI controls express scientific intent through
the existing DSL/IR and public API. Provider recipes, binding, execution, and
normalization stay in their current owners. Scientific displays consume normalized
Portfolios and their presentation projections. Preserve provider-labelled counts,
measurement distinctions, conflicting evidence, and record provenance.

The older `ui_product_plan.md` remains a historical product plan; this document
tracks the current implementation sequence. Some of its original prototype-only
assumptions have already been superseded by normalized Portfolio views.

## Small branches

| Branch | Reviewable outcome |
| --- | --- |
| `refactor/ui-01-dsl-validation` | Repair the validator's invalid default DSL, use `validate_dsl`, add actual offline planning, and document existing UI entry points. |
| `refactor/ui-02-session-execution` | Make execution and continuation belong to one browser session and the selected prior result. Add validation before execution and useful failure feedback. |
| `refactor/ui-03-workspace-navigation` | Integrate investigation, candidate results, and object inspection with clear navigation and evidence labels. |
| `refactor/ui-04-candidate-triage` | Add filtering, sorting, and candidate selection using shared scientific presentation projections. |
| `refactor/ui-05-portfolio-layout` | Refine the object header, scientific summary, photometry, classification, and provenance hierarchy. |
| `refactor/ui-06-enrichment` | Offer capability-aware enrichment and continuation; show new evidence and optional-call warnings. |
| `refactor/ui-07-export-polish` | Add canonical Portfolio export and complete empty, loading, and error states; review accessibility and responsive layout. |

Each branch is rebased on merged main before the next one begins. Split any row
further when the actual change becomes too large for one focused review. Visual
choices are reviewed locally against existing real captured evidence before live
provider calls.

## First branch

The standalone validator accepts complete programs, not continuation fragments.
It checks parsing before calling the public facade, so it cannot accidentally
inherit an active workflow held by another session in the same process. It uses
one capability graph for public validation and planning. Successful compilation
is distinguished from successful planning. Technical evidence is available in
an expander; neither operation makes provider calls or proves provider uptime.

The main investigation page still needs session-safe execution. Its current
`continue_from` argument controls the display but is not passed to execution;
the public facade currently stores an active workflow in process-local state.
Branch 02 establishes an explicit session-owned orchestration context at the
API boundary. The UI does not manipulate private facade globals.

## Branch 02 progress

`refactor/ui-02-session-execution` adds explicit `continue_from` to the public
facade. Streamlit validation and execution now use the editor's own prior result
or explicit `None`, without consulting or replacing compatibility state. Failed
submissions retain the prior view, successful parent reruns clear old descendant
results, and supplementary warnings are visible. Script callers that omit the
argument retain their existing behavior. The [session execution runbook](ui_session_execution.md)
describes local checks and the unchanged incomplete-prefix refusal policy.

## Local verification and handoff

The user runs tests, Streamlit, provider acceptance, GitHub pushes, PR creation,
and squash merges locally. No tests or broker calls were run while preparing
branch 01.

Branch 01 adds the validator file to the DSL CI path filter. That runs the
existing backend contracts and package check; it does not provide visual UI
coverage. The local Streamlit review below checks the page itself.

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_public_api.py \
  tests/test_dsl_capability_validation.py \
  tests/test_orchestration_planner.py

PYTHONPATH=. python -m streamlit run alertissimo/app_dsl.py
```

Check the default example, malformed DSL, an unknown scientific reference, and
a valid but unsupported/deferred request. The default should reach planning;
invalid requests should explain their failure. A clause-only fragment must be
rejected as an incomplete workflow. Detailed reports should remain collapsed
until requested. Validation must work without provider credentials.

Then open `app_search.py` to review the existing UI before branch 02. That page
can issue live calls when a DSL request is submitted.
