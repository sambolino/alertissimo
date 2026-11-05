---
name: provider-contract-change
description: Change or audit Alertissimo provider endpoints, mappings, encoders and semantic recipes while preserving evidence and completeness. Use for broker/survey integrations and native filter or pagination fixes.
---

Read root `AGENTS.md` and `ARCHITECTURE.md`, then the relevant provider's
`endpoints.yaml`, `mappings.yaml`, `capabilities.yaml` and recorded contract tests.

1. Trace the actual upstream parameter/response contract from a primary source
   or captured evidence. Keep separate audits for broker and survey.
2. Put physical API details in endpoints, scientific field meaning in mappings,
   and finite realizations/material/completeness claims in provider capabilities.
   Keep transformations pure. Never add broker switches to planner/UI code.
3. Preserve IDs and assertions. Do not promote catalogue context into candidate
   classification, turn raw reliability into probability, or invent missing data.
4. Check request binding, projection, identity multiplicity, pagination, time
   bounds, native/residual equivalence, and unknown/error outcomes. A native
   filter may provide a superset; keep the original local scientific check.
5. Reproduce the defect with frozen or clearly synthetic payloads. Compare native
   and local selection over the same complete controlled population.
6. Run relevant provider/transform/recipe tests, mapping validation and packaging
   when resources change. Distinguish a diagnostic page from full live acceptance.

Use `PYTHONPATH=. python -m alertissimo.data_layer.runtime.mapping_schema --all`
for provider mapping validation. Select matching `test_*registry_architecture`,
`test_*semantic_search`, normalization and endpoint tests as appropriate.
Do not seek credentials or claim live success from offline fixtures. Hand off the
tested revision, admitted/guarded requests and the user's git/gh commands.
