# Admit required discovery parameters supplied by predicates

A discovery recipe could not load when an endpoint required a parameter supplied
only by a predicate binding. The loader now accepts that declared source, while
request admission checks whether the actual predicate supplies it. A declaration
alone never makes an otherwise unbound request runnable.

This is the first half of PR 02 in the
[discovery integration plan](discovery_integration_plan.md), based on main
`1673fa0` (PR #293). Time binding and clock/replay handling are the next small
branch, 02b. No production provider recipe is activated in this branch.

## Behavior

- The recipe compiler counts a predicate binding as a possible assignment only
  for the required discovery call that owns it. Other calls still need their
  own assignments/defaults. Existing assignment/fixed-value conflict checks remain.
- Capability validation uses the existing pure predicate realizer to check
  mandatory predicate-supplied inputs. Planning uses the same realizer and call
  bindings. Missing assignments produce a deferred capability diagnostic naming
  the physical parameters before provider execution.
- Eligible comparisons and safe conjunctions supply their parameters. Conflicting
  values, unsupported operators or qualifier translations, and mandatory inputs
  hidden in residual OR/NOT expressions fail admission. No Boolean algebra or
  new predicate meaning is introduced.
- The binder retains its required-input guard. A null default no longer counts as
  a usable required value, consistent with the compiler and CapabilityGraph;
  legitimate non-null defaults such as zero and false retain their existing meaning.
- No new architecture layer, intermediate model, YAML syntax, parameter registry,
  public API argument, or scientific DSL construct was added. The only runtime
  changes are in the existing recipe compiler, capability validation, and binder.

## Verification handoff

Tests, package builds, apps, and live calls were not run during preparation.
Python AST and Git whitespace checks were performed. Run locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_required_predicate_bindings.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_predicate_recipes.py \
  tests/test_orchestration_discovery_eligibility.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_orchestration_binding.py \
  tests/test_dsl_predicate_realization.py \
  tests/test_orchestration_residual_pruning.py
```

The new regressions temporarily require ALeRCE's `class_name` parameter in a local
provider copy. They cover recipe compilation, static IR and public API admission,
binding and plan serialization, missing/conflicting/qualified inputs, preserved
residual predicates, no-network failures, null defaults, and refusal to borrow
predicate inputs for non-discovery calls or fall back to legacy tags.

These test declarations do not change the production ALeRCE contract. They do not
activate Fink's class-search endpoint or establish its classification-population,
time-window, or completeness guarantees. Those remain the responsibility of the
subsequent provider branches. No additional live broker acceptance is required
for this declaration/admission change.

The existing DSL CI job includes the new `test_orchestration_*.py` regression and
the touched runtime files. Package structure and runtime resource inclusion are
unchanged.
