# Recipe classification retrieval (branch 06b)

Branch: `refactor/recipes-06b-classification`.
Base: `main` at `237831d` (PR #262).

This increment activates `get_classification` recipes for the six provider/survey
paths with mapped classification material. Search and position endpoints are no
longer fresh classification retrieval alternatives merely because they map a
classification record. ANTARES has no mapped classification retrieval and remains
unsupported.

| Provider | Authored targeted calls | Classifier evidence |
| --- | --- | --- |
| ALeRCE/LSST | `query_probabilities` | Dynamic producer; no declared classifier filter |
| ALeRCE/ZTF | `query_probabilities`, `query_object` | Dynamic producer; only the probability recipe translates `step.classifier` |
| Fink/LSST | `sources`, `objects` | Fixed producer `fink` |
| Fink/ZTF | `objects` | Fixed producers from endpoint mappings, including `fink` and `sextractor` |
| Lasair/LSST | `object`, `sherlock_object` | Fixed producer `sherlock` |
| Lasair/ZTF | `object`, `objects`, `sherlock_object`, `sherlock_objects` | Fixed producers `sherlock` and, on generic object retrievals, `tns` |

Recipes keep the existing IR operation, target fields, classifier field, endpoint
contracts, and mapping qualifiers. There is no added selector language or repeated
semantic type:

```yaml
get_classification:
  - calls:
      - endpoint: query_probabilities
        params:
          oid: {from: step.target.ids}
          classifier: {from: step.classifier}
```

Activation requires one required call with classification mappings, a direct
target-identity input, and the existing `target_id` binding role. ALeRCE probability
endpoints now declare that role on their existing `oid` parameters. Their physical
types, signatures, defaults, and integer/string coercion are preserved.

A requested classifier can match a fixed mapping qualifier case-insensitively.
A dynamic qualifier requires an authored `step.classifier` assignment to a
declared server-filter parameter. Parameter existence, a provider default, and
dynamic output mapping alone do not establish that selector. ALeRCE/LSST qualified
standalone retrieval therefore remains deferred. Unqualified probability retrieval
is feasible and uses the existing scalar fan-out.

For multiple explicit targets, collection alternatives retain the existing
preference. A singular-only endpoint still fans out. Other equal alternatives
remain ambiguous; this includes Fink/LSST, unqualified ALeRCE/ZTF, and several
Lasair requests. Recipe order never resolves a tie. Migrated providers cannot fall
back to their old endpoint tags when a recipe is infeasible.

Workflow planning can still reuse an actual earlier search execution for a
targetless qualified classification Get when its positive predicate establishes
that dynamic producer. This uses the existing execution proof and reuse metadata;
it does not turn the search into a fresh retrieval recipe. The proof requires an
explicit provider/survey source, a feasible unqualified retrieval recipe, exactly
one matching required search plan, matching request constants, and an unchanged
candidate population. Negated predicates and Filter/Match/Confirm population
changes cannot establish this reuse. Both IR steps remain present, while the Get
owns no new invocation. The existing motivating ALeRCE pipeline remains covered by
execution-coalescing and DSL smoke suites.

Unqualified retrievals can also bind identities from earlier candidate material.
Recipe input paths and dependency references survive workflow JSON round trips.
Binding, runner, executor, and normalizer reuse their existing implementations.
Mappings describe possible material; they do not guarantee populated classifier
results, response projections, or scientific conclusions.

## Local workflow

Download `recipes-06b-classification.bundle`, then run in the repository with your
virtual environment active:

```bash
recipe_branch=refactor/recipes-06b-classification
recipe_bundle="$HOME/Downloads/recipes-06b-classification.bundle"
git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python -m pytest -q \
  tests/test_orchestration_classification_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_capability_validation.py \
  tests/test_orchestration_planner.py \
  tests/test_orchestration_binding.py \
  tests/test_orchestration_execution_coalescing.py \
  tests/test_dsl_smoke_pipeline.py \
  tests/test_alerce_classification_mappings.py
```

After those pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Activate targeted classification retrieval recipes" \
  --body 'Activates classification retrieval recipes using target bindings, mapping qualifiers, and explicit classifier filter assignments. Preserves genuine ambiguity, candidate binding, and proven search material reuse. Validation: focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If checks have not appeared immediately after pushing, rerun the watch command
once GitHub queues them. After both checks pass:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

Author-side inspection: Python/YAML syntax parsing and `git diff --check` only.
Tests were not executed by the authoring agent. Next increment: crossmatch recipes.
