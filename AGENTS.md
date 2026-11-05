# Working on Alertissimo

Read [ARCHITECTURE.md](ARCHITECTURE.md) for the current owners, scientific
invariants, retired interfaces and functional priorities before changing code.

## Scope and autonomy

- Follow the user's current scope. Complete authorized fixes without repeated
  permission requests; clarify missing scientific choices instead of inventing them.
- Deployment is deploy-yourself. Future NLP may use the project's LLM server and
  emit validated DSL. Do not add hosted session/database/service infrastructure.
- Coarse classification normalization, universal `best` and requested DSL changes
  are functional priorities. Do not silently substitute unreviewed thresholds,
  taxonomy, model precedence or cross-method score comparisons.
- Use a focused branch from current main. Do not mutate GitHub PRs, push or merge
  through tools. Supply reviewable commits/bundles and exact git/gh commands.

## Scientific and architectural contracts

- Keep one public facade, canonical WorkflowIR, ontology and normalized Portfolio.
  Preserve existing semantic IDs; prefer additive mappings over renaming.
- Provider details belong in declarations and pure adapters, not broker switches
  in the DSL, planner or UI. Do not restore retired `core` execution code.
- Keep scientific extraction in shared presentation. Display dictionaries are
  transient formatting, not another domain model or scientific truth.
- Preserve survey/object identity, provenance, unknown evidence, assertion-local
  comparisons, material lineage, reuse and exact time/completeness semantics.
- Preserve upstream outputs and distinguish probability, score, rank and timing.
- Preserve original documents as history when replacing stale instructions.

## Repository procedures

Read the relevant procedure; do not load every historical plan:

| Task | Procedure |
|---|---|
| Provider declarations, mappings, encoders | `.agents/skills/provider-contract-change/SKILL.md` |
| DSL, planning, execution, continuation | `.agents/skills/semantic-orchestration-change/SKILL.md` |
| Scientific UI, charts, fixtures | `.agents/skills/scientific-ui-change/SKILL.md` |

These are repository-owned skills, portable with a checkout. They do not install
anything into a personal ChatGPT skill directory.

## Verification and handoff

Use `rg` and trace callers/contracts before editing. Add meaningful regressions
for scientific defects; never weaken checks or relabel failures to obtain PASS.
Run focused owner checks, then appropriate integration/release checks. Do not
repeat overlapping suites without a change or unresolved concern that needs it.
State actual test/live evidence, tested revision and limits. Parsing, planning,
empty results and diagnostic pages do not establish nonempty live acceptance.
Update authoritative ownership guidance when it changes; retain historical plans
with clear pointers instead of creating competing architecture documents.
