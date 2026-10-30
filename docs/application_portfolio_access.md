# Application access to scientific results

Step 08, branch `feat/integration-08-portfolio-access`, based on integration
`4d93b51` / PR #325. Target `integration/discovery-completion`.

Applications enter through `alertissimo.api.execute_dsl` and read
`DSLExecutionResult.portfolios`. This is the final material view of the current
workflow, including its candidate filters. Historical Step snapshots are execution
evidence; concatenating them can reintroduce rejected candidates and duplicates.
`validate_dsl` checks syntax, semantics and planning; it does not retrieve results.

The existing Portfolio, SemanticRecord, serialization and photometry helpers
already expose the required information. This change adds a checkout consumer
example and regressions. It changes no ontology, DSL, planning, provider mappings
or domain models. Helpers in `examples/application_portfolio_access.py` illustrate
consumer choices; they are not a new installed Alertissimo API.

## One candidate and several candidates

```python
from alertissimo.api import execute_dsl
from examples.application_portfolio_access import candidate_identity, select_candidate

result = execute_dsl(
    "objects ZTF21abfmbix, ZTF20acpwljl from ztf via fink\n"
    "with lightcurve via fink\n",
    continue_from=None,
)
for candidate in result.portfolios:
    origin, object_id = candidate_identity(candidate)
    print(origin, object_id, len(candidate.records))

# Selection happens before any extraction. The returned object is the original
# Portfolio, with all its records and execution provenance.
candidate = select_candidate(result.portfolios, origin="ztf", object_id="ZTF21abfmbix")
```

The same route works for a lookup with one ID or the surviving candidates from a
discovery workflow. The identity is `(survey, object ID)`, not a bare ID or the
Portfolio's internal identifier. Summary records establish ownership; a crossmatch
ID can identify an associated catalogue source instead. Several provider summaries
can establish the same candidate. Missing, mixed, or ambiguous summary identities
and missing/duplicate requested matches fail explicitly in this example.

An explicit ID selects a Portfolio; it must never become a label attached to the
union of several candidates. Survey identity and exact qualified semantic types
remain intact. A classification's producer is not automatically a survey: for
example `classification@lc_classifier:alerce` and `classification@fink`.

## Records, assertions and provenance

```python
from examples.application_portfolio_access import record_frame, classification_records

summaries = record_frame(candidate, "summary")
classifications = record_frame(candidate, "classification")
crossmatches = record_frame(candidate, "crossmatch")
measurements = record_frame(candidate, "measurement")

# A version is an exact identity, not a sortable recency value. This can be empty
# if this candidate has no such ALeRCE material; it does not trigger retrieval.
assertions = classification_records(
    candidate, semantic_type="classification@lc_classifier:alerce", version="v1",
)
```

`record_frame` is a Pandas view over canonical serialized records. Each row keeps
`internal_record_id`, the full `semantic_type`, all fields under `fields.…`, and
the execution/payload/path/index under `source.…`. Object dtype preserves large
integer source IDs when other records lack that field. A table can represent
missing cells as NaN; use `record.has(path)` and `record.get(path)` or canonical
JSON when absent and explicit null must remain distinct. Empty views have no rows
and may have no columns. No semantic fields are manufactured to fill an empty view.

Classification selection uses the exact producer/channel-qualified type and,
when requested, the producer's version. It returns **all** matches, including
conflicts. It never assumes the first record is current, orders version strings,
or substitutes retrieval time or Fink science-pipeline version for assertion time
or classifier version.

For alert-dependent classifications, an application can first select a measurement
by its explicit observation-time policy, then request classifications from that
same source row:

```python
# record_id comes from a chosen plotted point, after the application's time rule.
measurement = candidate.get_record(record_id)
if measurement is None or measurement.internal_source is None:
    raise ValueError("chosen measurement has no source-row evidence")
same_alert_assertions = classification_records(
    candidate, semantic_type="classification@fink", source=measurement.internal_source,
)
execution = candidate.execution(measurement.internal_source.internal_execution_id)
```

Source-row correlation compares the whole `InternalRecordSource`, including the
execution, payload key/path and row index. Index zero alone proves no relationship
across calls. It does not infer that an independently returned ALeRCE classifier
assertion belongs to a particular measurement. Without a dated assertion or
verified link to dated evidence, preserve the assertions and report that a newest
choice is unavailable. Missing versions remain missing. All supplied source rows,
including older assertions, remain available on the Portfolio.

The same source-row comparison can correlate a Fink measurement and its Pan-STARRS
record before applying a consumer's combined cuts. Preserve separation units,
star/galaxy missingness, and negative sentinels; a sentinel is not a close match.
The [reference inventory](reference_workflow_material.md) explains why a candidate
filter spanning several record families is not automatically a same-alert cut.

## Photometry, limits and counts

```python
from alertissimo.data_layer.presentation import portfolio_lightcurve_dataframe

points = portfolio_lightcurve_dataframe(candidate)
# Neutral plotting columns include record_id, semantic_type, mjd, band,
# measurement_kind (ordinary/forced), quantity (mag/flux), value and error.
if not points.empty:
    points_with_source = points.merge(
        measurements, left_on="record_id", right_on="internal_record_id",
        validate="many_to_one",
    )
```

This reuses the existing semantic-path projection, without parsing broker payload
keys. It keeps ordinary and forced values distinct, including negative forced
flux. Non-detections remain `measurement` records with limit fields such as
`photometry.g.limit.mag`; the current plotting helper does not turn limits into
ordinary magnitudes or plot them as detections. All their fields and source
metadata are available in `measurements`. Native `lightcurve` records and nested
points also remain in the Portfolio/JSON; do not concatenate native points and
atomic measurements as if they were independent observations.

Reported counts are summary evidence, not `len(points)` or the number of loaded
measurement records. Inspect `fields.detection_count` with its qualified summary,
`fields.time.last_mjd`, and source row. Several rows can be historical snapshots;
this example retains them all. It does not sum them, replace them with loaded
counts, or infer newest from payload order or largest count. A plotting table can
have several quantities per measurement, so even its length is not an observation
count. Candidate selection retains every measurement of each survivor.

`with enrichment` uses the current abstract family and expands to admitted concrete
Gets. It is not a guarantee that every conceivable supplement runs. In particular,
the inherited-target ALeRCE lightcurve Get omits optional singular forced photometry
under the existing cardinality policy; an explicitly targeted singleton IR Get can
admit it. See the [07c unit regression](integration_07c_alerce_distance_units.md).
No new forced-photometry surface noun or measurement subtype is added here.

## Serialization and runnable checkout example

```python
from alertissimo.data_layer.runtime.serialization import portfolio_to_dict, portfolio_to_json

whole_turn = result.to_json()           # Final candidates plus workflow/run metadata.
one_candidate = portfolio_to_json(candidate)
wire_candidate = portfolio_to_dict(candidate)
```

Canonical serialization retains all semantic records, edges, qualifiers and
execution/source audit, including exact integer IDs and missing/null distinctions.
It does not export raw upstream payloads. CSV/DataFrames are presentation views,
not substitutes for that serialized scientific evidence.

With dependencies and local credentials configured, save a complete workflow in
`/tmp/application-workflow.dsl` and run:

```bash
PYTHONPATH=. python examples/application_portfolio_access.py /tmp/application-workflow.dsl \
  --origin ztf --object-id ZTF21abfmbix \
  > /tmp/alertissimo-selected-candidate.jsonl
```

Without the paired selection options it exports all final candidates, one canonical
Portfolio JSON document per line; a valid empty result emits no documents. Explicit
selection from an empty result is an error. Running the example executes the
workflow's provider calls. Importing its helpers does not execute anything.

Nucleuswatch's external bridge should adopt per-candidate selection and explicit
classification policy before translating into its own models. This branch does
not modify Bibin's repository or introduce `BrokerResult` into Alertissimo.

## Local verification

The new tests cover a synthetic two-candidate/multi-survey ownership example,
classification order/version/source rules, ordinary/forced/limit views, exact
integer source IDs, reported counts, source joins and canonical serialization.
Public `execute_dsl` cases use recorded Fink row structure with deliberately
modified IDs, magnitudes and labels through a fake transport, for one and two
candidates. These are isolation fixtures, not new captures or completeness claims.

No tests, project imports, builds, applications or provider calls ran during
preparation. Only source inspection, AST/YAML parsing, whitespace and Git bundle
verification were performed. Run locally:

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_application_portfolio_access.py \
  tests/test_portfolio_lightcurve.py \
  tests/test_portfolio_serialization.py \
  tests/test_dsl_public_api_serialization.py \
  tests/test_target_bound_partition_identity.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-integration-08-tests.log
```

The existing UI workflow has Pandas and now includes the new example regression
and existing photometry projection tests. Keep focused local testing and squash
into integration; another shared CI run is not needed for this example-only step.
Final CI and live acceptance remain separate requirements before main.
