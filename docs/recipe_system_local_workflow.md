# Local workflow for branch 01

Run from your existing Alertissimo checkout, with your usual Python environment.
The supplied Git bundle contains only this branch's changes and requires baseline
commit `18713d4a6237984fc60ff62979364fa3e25ddaf3`, which is available from `main`.
Download `recipes-01-output-index.bundle` and adjust the path below.

Import and inspect:

```bash
recipe_branch=refactor/recipes-01-output-index
recipe_bundle="$HOME/Downloads/recipes-01-output-index.bundle"

git fetch origin main
git bundle verify "$recipe_bundle"
git fetch "$recipe_bundle" "$recipe_branch:$recipe_branch"
git switch "$recipe_branch"
git diff --stat origin/main...HEAD
git diff origin/main...HEAD -- alertissimo/data_layer/runtime/capability_graph.py tests/test_capability_graph.py
```

Run the focused verification locally. The editing environment did not run it:

```bash
git diff --check origin/main...HEAD
PYTHONPATH=. python -m pytest -q tests/test_capability_graph.py
```

This branch adds `CapabilityGraph.fields_for_endpoint()` and checks that Lasair's
thin cone output does not inherit the query endpoint's richer summary fields.
It does not change endpoint selection or live requests, so no live API run is
needed for this branch.

After the commands pass, push and create the PR:

```bash
git push -u origin "$recipe_branch"

recipe_pr_body=$(mktemp)
cat > "$recipe_pr_body" <<'EOF'
The capability graph currently exposes record fields aggregated across endpoints, which is insufficient evidence for field-aware recipe planning. Add an endpoint-specific field-mapping query that preserves payload and qualified semantic-path evidence without changing planning behavior.

Include the incremental recipe migration plan and local workflow. A mapping remains evidence of a possible output, not guaranteed presence under every projection or response.

Validation: run `PYTHONPATH=. python -m pytest -q tests/test_capability_graph.py` and `git diff --check origin/main...HEAD` locally before submitting. Tests were not run in the editing environment.
EOF

gh pr create --base main --head "$recipe_branch" \
  --title "Expose endpoint-specific field evidence for recipe planning" \
  --body-file "$recipe_pr_body"
rm "$recipe_pr_body"
```

After review and passing required checks, merge and refresh the local main branch:

```bash
gh pr checks "$recipe_branch" --watch
gh pr merge "$recipe_branch" --squash --delete-branch
git switch main
git pull --ff-only origin main
```

If checks or merge fail, stop there and return the output. Do not bypass required
checks. PR creation and merging above are commands for the user; neither was
performed in the editing environment.

Subsequent implementation branches start from the newly merged `main`. Their
handoffs will provide their own bundle, exact focused commands, and PR text.
Do not create all future branches from today's baseline.
