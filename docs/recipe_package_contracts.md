# Installed-wheel recipe contracts (branch 10n)

Branch: `refactor/recipes-10n-package-contracts`, based on merged `main` at
`c92ed18` (PR #286).

The release package checker previously validated one ALeRCE ZTF DSL program from
an installed wheel. Extend it to compare packaged runtime declarations with the
checkout and load recipe contracts for all eight broker/survey pairs. Require the
common cone, lookup, lightcurve, and confirmation declarations, then validate and
plan a cone DSL program for each source. Every resulting physical plan must carry
explicit recipe parameter sources. Preserve the existing latest-selection example.

DSL CI runs the checker and watches its script and packaging inputs. Its focused
dependencies add only the setuptools/wheel build tools. Wheel building and temporary
installation use --no-deps; no provider client stack is installed by the check.
The checker performs no provider API calls, physical value encoding, or result
normalization. It verifies package fidelity and static recipe planning.

README replaces the retired request-mapping description and links a current
runtime architecture guide. Historical migration documents remain unchanged.
There are no runtime or provider declaration changes. No tests or wheel build
were run here. Outer and embedded Python syntax, workflow YAML, declaration
invariance, Markdown references, whitespace, local test paths, handoff shell
syntax, and bundle structure were checked.

## Local handoff

```bash
recipe_branch=refactor/recipes-10n-package-contracts
recipe_bundle="$HOME/Downloads/recipes-10n-package-contracts.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git rebase origin/main
git diff --check origin/main...HEAD

PYTHONPATH=. python scripts/check_release_package.py
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_public_api.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_recipe_registry.py \
  tests/test_orchestration_cone_recipes.py \
  tests/test_orchestration_composite_cone_recipes.py
```

If build tools are missing in the local environment:

```bash
python -m pip install 'setuptools>=69.5.1' wheel
```

Then rerun the package check. After all local checks pass:

```bash
git push -u origin "$recipe_branch"
gh pr create --base main --head "$recipe_branch" \
  --title "Verify installed-wheel recipe contracts" \
  --body 'Compare packaged runtime declarations with the checkout and validate/plan cone recipes for all eight broker/survey pairs from an isolated wheel install. Add the offline package check to DSL CI and watch packaging inputs. Document the active recipe architecture and retained compatibility boundaries. Runtime and provider declarations are unchanged. Validation: package check and focused suites run locally.'
gh pr checks "$recipe_branch" --watch
```

If no checks appear yet, rerun the watch command once workflows register.
After review and passing checks:

```bash
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```
