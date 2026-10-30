# Live discovery acceptance and final verification

Step 09b, branch `feat/integration-09b-live-acceptance`, based on integration
`b4ada2a` / PR #327. Target `integration/discovery-completion`. This branch adds
an explicit acceptance script and its offline tests. It changes no backend,
ontology, provider recipes, mappings, transport policy or scientific DSL rules.

`scripts/live_dsl_discovery.py` calls the public `validate_dsl` and `execute_dsl`
facade. It does not construct an IR, plan or bound provider request itself.
Existing finalized Portfolio identities and retained execution provenance are
read for acceptance checks and reporting. Tests substitute fixture transports;
preparing this branch contacted no providers and ran no project code.

## Interface and scenarios

```bash
PYTHONPATH=. python scripts/live_dsl_discovery.py --list
PYTHONPATH=. python scripts/live_dsl_discovery.py --validate-only
```

Both commands are offline. `--validate-only` writes input DSL and planning outcomes
and identifies its phase as validation; a PASS here is not live evidence.
Running without either option executes the selected scenarios, or all eight if
no `--scenario` is given. Repeat `--scenario NAME` to select several.

| Scenario | Live workflow and limits |
| --- | --- |
| `alerce-classification` | Original explicit ZTF lookup, once unconstrained and once `from lc_classifier`; no invented classifier keyword, ordering or winner |
| `fink-class-time` | Original SN-candidate `within 7d`, with histories/classification; the existing `n=100` alert-row saturation guard remains active |
| `discovery-filter-retrieve` | Default one-hour Fink SN stream, `quality.real_bogus >= 0.9` candidate filter, then survivor lightcurves/classification |
| `multi-object-consumer` | Explicit `ZTF21abfmbix` and `ZTF20acpwljl`, with Fink lightcurves; separate summaries, identified measurements and disjoint detection IDs |
| `alerce-ztf-time` | Five-arcsecond default cone, one-hour temporal selection, `latest 3`, then available survivor history |
| `lasair-ztf-time` | Same spatial/temporal intent through required Lasair summary/history contracts; requires `LASAIR_ZTF_TOKEN` |
| `antares-ztf-time` | Small numeric RA/Dec box with ZTF identity scope, temporal history proof, `latest 3`, then survivor lightcurves |
| `fink-cutouts` | Explicit object lookup, fixed JSON `data_product` retrieval, three named science/template/difference stamp arrays |

The default sky field is RA `124.87996115142856`, Dec `-6.0205001`, half-width/radius
`5` arcsec. These are known example coordinates, not a promise of recent activity.
A short current window can legitimately return no candidates there. Use
`--ra`, `--dec`, `--radius-arcsec` for a field containing relevant objects or paired
historical bounds to exercise its available history. The ANTARES field is an
RA/Dec rectangle, with the numeric half-width on each coordinate; it is not an
exact spherical cone. This runner rejects fields crossing coordinate boundaries.

`--window-hours N` changes the short windows, not the original seven-day Fink
regression. `--latest N` changes candidate selection on the three `*-ztf-time`
scenarios; it does not truncate discovery early or override physical row limits.
`--time-mode first` or `--time-mode last` applies only to those three scenarios.
Fink remains on its admitted default detection-window semantics. Histories retain
all measurements of survivors, including times outside the membership interval.
The script's measurements and counts are evidence views, not new scientific
selection operations.

Existing pagination safety boundaries remain unchanged: normally 1,000 rows per
automatic page and at most three pages, subject to each endpoint declaration.
Reaching a safety boundary fails explicitly. Individual histories and ANTARES
lazy relationships may involve more HTTP requests than the visible native-call
count. `latest 3` is not a guarantee of three cheap provider calls.

Live execution uses a POSIX per-workflow deadline, default 180 seconds; change
with `--timeout-seconds`. It does not change backend request contracts. Validation
and listing also work without POSIX timers. The two classification workflows have
separate deadlines, and successful earlier results are retained if a later one
fails.

## Evidence and outcomes

Each invocation samples one UTC reference instant and passes it explicitly to
every public execution. Relative windows therefore share a recorded reference;
no later scenario silently uses a new now. Absolute windows record their actual
UTC bounds. `--start ISO_DATETIME` and `--stop ISO_DATETIME` must be paired,
timezone-aware, and ordered. They affect windowed scenarios only. A fixed override
is marked in metadata; a one-day override is not reported as the original
seven-day regression.

The script reads the checkout `.env` with existing variable names and preserves
already-set environment values. It does not introduce `LASAIR_TOKEN` as an alias.
Output defaults to a fresh temporary directory. `--output-dir PATH` must be new
or empty so earlier evidence cannot be overwritten.

Artifacts include:

- `run.json`: revision, distribution versions, reference UTC, invocation options
  and incremental scenario summaries.
- `SCENARIO/00.dsl` (and `01.dsl` for the second classification query): exact input.
- `SCENARIO/00.result.json`: the canonical final semantic result, saved before
  invariant checks. It retains Portfolio records, qualifiers and execution audit,
  including product arrays where returned; raw upstream payloads are not exported.
- `SCENARIO/summary.json`: phase, bounds, candidate identities, record/Step counts,
  physical execution IDs, request parameters and response metadata. Execution
  provenance is retained even when the final candidate result is empty. Shared
  executions can appear in several semantic occurrences; the unique count uses
  execution IDs and is not an HTTP-request count.
- `SCENARIO/error.log`: failure traceback, when present. Known Lasair credential
  values are redacted; request headers and environment contents are not exported.

| Status | Meaning |
| --- | --- |
| PASS | Offline planning passed in validation mode, or a nonempty live workflow satisfied the named checks in live mode |
| FAIL | Planning, binding, malformed/incomplete evidence or invariant failure; saturation remains a failed request, not a successful sample |
| UNAVAILABLE | Observable provider/network timeout, connection failure, HTTP 408/429/5xx or per-workflow deadline |
| SKIP | Missing credentials/access, valid empty population, missing requested live material, or incomplete optional supplements; no successful nonempty acceptance is claimed |

By default the diagnostic sweep returns 1 for FAIL, otherwise 0, while still
reporting every unavailable/skipped scenario. `--require-all-pass` also returns 2
when any scenario is SKIP or UNAVAILABLE. Review phase and statuses, not just a
zero exit code. A valid empty discovery is correct backend behavior but cannot
exercise a downstream nonempty acceptance case. The recorded suite tests the
empty and incomplete branches deterministically.

## Local handoff

Run focused offline checks before pushing the small PR:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_dsl_live_discovery.py \
  tests/test_discovery_integration_acceptance.py \
  tests/test_dsl_live_acceptance.py \
  2>&1 | tee /tmp/alertissimo-integration-09b-tests.log
```

After squash, use a fresh evidence root. Keep logs outside each script-owned
subdirectory so `tee` does not make that output directory nonempty in advance.

```bash
acceptance_dir=$(mktemp -d /tmp/alertissimo-discovery-final.XXXXXX)
set -o pipefail

PYTHONPATH=. python scripts/live_dsl_discovery.py --list
PYTHONPATH=. python scripts/live_dsl_discovery.py --validate-only \
  --output-dir "$acceptance_dir/validation" \
  2>&1 | tee "$acceptance_dir/validation.log"

PYTHONPATH=. python scripts/live_dsl_discovery.py \
  --scenario alerce-classification \
  --scenario fink-class-time \
  --scenario discovery-filter-retrieve \
  --scenario multi-object-consumer \
  --scenario fink-cutouts \
  --output-dir "$acceptance_dir/reference-live" \
  2>&1 | tee "$acceptance_dir/reference-live.log"
```

If the seven-day Fink population saturates, keep that failed request's evidence.
A separate shorter fixed-window run can exercise the admitted acquisition path;
it does not replace the original seven-day outcome. For an actual one-hour current
comparison, these paired bounds are generated once and preserved by the script:

```bash
discovery_stop=$(date -u +%Y-%m-%dT%H:%M:%SZ)
discovery_start=$(date -u -d "$discovery_stop - 1 hour" +%Y-%m-%dT%H:%M:%SZ)
PYTHONPATH=. python scripts/live_dsl_discovery.py \
  --scenario fink-class-time \
  --start "$discovery_start" --stop "$discovery_stop" \
  --output-dir "$acceptance_dir/fink-fixed-hour" \
  2>&1 | tee "$acceptance_dir/fink-fixed-hour.log"
```

Choose dates/field containing real history to exercise default, first and last
membership and global latest on the three audited ZTF routes. The following
commands are valid as written with default current one-hour windows; SKIP is
possible when the example field has no matching observations. Add paired historical
bounds and a chosen field when needed; do not claim those skipped branches passed.

```bash
for discovery_mode in detection first last; do
  PYTHONPATH=. python scripts/live_dsl_discovery.py \
    --scenario alerce-ztf-time \
    --scenario lasair-ztf-time \
    --scenario antares-ztf-time \
    --time-mode "$discovery_mode" \
    --output-dir "$acceptance_dir/time-$discovery_mode" \
    2>&1 | tee "$acceptance_dir/time-$discovery_mode.log"
done
```

The loop records each outcome; inspect every summary, because a later successful
command does not erase an earlier failure.

## Broader offline and final merge gate

Source inspection found pytest modules under `tests/`, with no pytest configuration
or collection hook enabling live calls. Provider-execution tests use fake REST
transports/native clients; the smoke runner defaults to `live=False`, and its
live-option tests intercept planning/execution or reject invalid requests. The
existing `test_dsl_live_*` names describe offline tests of live-script behavior.
This is a source audit, not an executed test result. Run the explicit test tree
and installed-wheel resource check locally:

```bash
PYTHONPATH=. python -m pytest -q tests \
  2>&1 | tee "$acceptance_dir/offline-full.log"
PYTHONPATH=. python scripts/check_release_package.py \
  2>&1 | tee "$acceptance_dir/package.log"
PYTHONPATH=. python scripts/live_dsl_facade_acceptance.py \
  2>&1 | tee "$acceptance_dir/facade-live.log"
```

The final command is explicitly live; the preceding two do not call brokers.
Report exact revision, offline/package outcomes, and live FAIL/UNAVAILABLE/SKIP
separately. Do not install additional clients merely to turn a recorded replay
into a live test.

After reviewing this evidence, consult on classification joins and additional
Rubin discovery before implementing either. If the agreed scope is complete,
remove the three temporary integration-base CI exclusions in a final cleanup
commit, update against main, open the integration-to-main PR, and run all three
applicable checks there. Do not rerun obsolete workflow SHAs or bypass required
checks. This 09b feature PR still targets integration with automatic CI excluded;
no main merge or remote operation is performed by this script.
