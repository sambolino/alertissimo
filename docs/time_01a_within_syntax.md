# Preserve explicit within selection intent

This is **Time 01a**, based on merged Lasair discovery PR #304, main `92b4879`.
The shared Time 01 milestone is split into syntax/IR admission here and
material-based membership verification in Time 01b. Provider activation follows
those prerequisites, beginning with ALeRCE ZTF. No broker calls ran here.

## User-facing meaning

| Syntax | Intended candidate selection |
| --- | --- |
| `within 7d` | At least one detection in the last seven days |
| `first within 7d` | The selected source's earliest detection is in the interval |
| `last within 7d` | The selected source's latest detection is in the interval |

All three accept an absolute date pair. Bracketed and double-quoted forms are now
represented in the grammar, alongside the existing unbracketed pair:

```text
within ["2026-10-01T00:00:00Z", "2026-10-08T00:00:00Z"]
first within [2026-10-01T00:00:00Z, 2026-10-08T00:00:00Z]
last within 2026-10-01T00:00:00Z, 2026-10-08T00:00:00Z
```

These are syntax examples. They do not claim that first/last provider execution
is active in this prerequisite branch. The default has no additional keyword;
`any within` is not accepted. Candidate selection will retain every returned
measurement belonging to a surviving object.

## Changes

- The current WithinClause and TimeContext gain `mode`, default `detection`,
  with `first` and `last` alternatives. Existing serialized intent without the
  field reads as the default. Mode is part of IR equality/serialization, so a
  continued occurrence cannot silently change detection existence to first/last.
- The existing parser lowers relative durations and absolute bounds without
  sampling now. Date strings are decoded with JSON string handling, not eval.
  Bracket delimiters cannot disappear inside a greedy unquoted bound token;
  leading whitespace cannot steal a quoted bound. Relative intent remains in IR.
- First/last remain candidate-scope clauses: forbidden on explicit lookup,
  after an explicit filter, and in continuation fragments. Existing duplicate
  within checks still apply. `match ... within` remains a separate tolerance.
- The existing temporal resolver preserves mode beside resolved start/end.
  Default physical ISO/JD/MJD encodings and the once-per-occurrence clock are
  unchanged. Explicit offset-aware bounds normalize through existing UTC code.
  Parsing a naive date remains distinct from admitting it for execution; the
  existing temporal validator rejects ambiguous naive bounds for encoded calls.
- Current capability admission explicitly defers first/last, and the existing
  detection-window encoder refuses them even if someone bypasses planning with
  a constructed plan. A native detection-time request is not proof of a native
  first/latest-history selector. No provider-name switch or implicit relabeling
  is added.

No new architecture layer, operation, endpoint, scientific record family,
dependency, or provider declaration is introduced. Existing Fink ZTF default
class/time discovery remains admitted and binds the same physical parameters.
The existing incremental semantic-prefix check needs no code change because the
mode now belongs to canonical intent.

## Exact boundary and next step

This branch completes parsing, IR representation, serialization, mode-preserving
bound resolution, and safe admission guards. It does **not** implement temporal
membership pruning or activate previously unavailable ALeRCE/Lasair windows.
The syntax/IR stage is intentionally a small review; it is not the completion
claim for the agreed default/first/last feature.

Next: **Time 01b**, membership checks in existing discovery finalization and the
minimum compiled evidence needed to admit an exact native selector or verify a
safe discovery superset. A positive in-window detection can prove existence;
absence needs complete relevant coverage. Summary history overlap alone cannot
prove a historical detection exists. Checks must precede latest selection,
preserve measurements and provenance, and use existing candidate ownership,
clock, and execution reuse. Provider branches then activate verified routes.
Classification joins and remaining Rubin discovery stay at the end of the
revised integration plan for discussion with Veljko first.

## Verification on Veljko's machine

No tests, builds, project imports, apps, or live provider requests ran here.
Python AST, YAML syntax, Git whitespace, and bundle checks were performed. The
new `test_dsl_within_modes.py` matches the existing DSL CI glob, and no duplicate
CI suite entry or packaging change is needed. The grammar was reviewed as source;
execute these parser/contract tests locally:

```bash
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_within_modes.py \
  tests/test_dsl_surface.py \
  tests/test_dsl_lowering.py \
  tests/test_discovery_time_bindings.py \
  tests/test_orchestration_ir_models.py \
  tests/test_orchestration_binding.py \
  tests/test_dsl_candidate_recipes.py \
  tests/test_fink_semantic_search.py \
  tests/test_api_continuation.py
```

Cases cover mode spelling/case, relative and both absolute syntaxes, leading
whitespace before quoted bounds, sub-day precision and explicit timezone offsets,
malformed/reversed dates, clause scope, legacy serialized defaults, invalid modes,
static validation without a clock, unchanged native Fink bindings, adapter refusal
of unsupported first/last intent, and continuation prefix protection.
