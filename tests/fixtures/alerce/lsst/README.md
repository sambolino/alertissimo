# Authoritative ALeRCE/LSST Python-client fixtures

These files are the JSON-serialized return values captured on **2026-08-11** from the official `alerce` **2.3.1** package, using `alerce.core.Alerce` through its multisurvey LSST route with `survey="lsst"`, `format="json"`, a finite 20-second HTTP timeout, and live OID `170587117485817955`. They are captured client return values, not schema-generated examples and not direct REST responses. `capture_manifest.json` records the calls and outcomes.

## Observed response shapes

| Call | Captured result |
|---|---|
| `query_objects` (requested OID only) | `list[2]`; both rows have the same `oid`, `tid`, and `sid`, and each carries a classification |
| `query_object` | `dict` with 15 scalar leaves |
| `query_detections` | `list[16]`, with 102 distinct scalar leaf names |
| `query_forced_photometry` | `list[10]`, with 14 distinct scalar leaf names |
| `query_non_detections` | `list[0]` |
| `query_lightcurve` | `detections=list[16]`, `non_detections=list[0]`, `forced_photometry=list[10]` |
| `query_probabilities` | `list[10]`, with 5 distinct scalar leaf names |
| `query_magstats` | `NotImplementedError: Multisurvey query_magstats not implemented.` |
| `query_features` | `NotImplementedError: Multisurvey query_features not implemented.` |

The object summary reports `n_det=16`, `n_forced=23`, and `n_non_det=0`. The 16 returned detections agree with `n_det`, and the empty non-detection result agrees with `n_non_det`. In contrast, both `query_forced_photometry` and the light-curve forced-photometry branch contain 10 rows, which does **not** equal `n_forced=23`. These fixtures establish only the observed 10 returned rows; they do not establish why the counts differ or that all forced measurements were returned.

The empty non-detection fixture is authoritative for this object only. It does not establish a concrete non-detection row shape or imply that the endpoint is globally empty. The client endpoint and all three LSST light-curve branches remain represented, while no non-empty row is fabricated.

## Leaf accounting

Counts are distinct observed scalar leaf paths after homogeneous list rows are collapsed. The light-curve total audits both populated delegated row families; its 116 branch leaves are structural at the bundle level and independently accounted by the nested definitions.

| Fixture/branch | Observed | Mapped | Intentionally unmapped | Delegated/structural | Unaccounted |
|---|---:|---:|---:|---:|---:|
| `query_objects` | 19 | 5 | 14 | 0 | 0 |
| `query_object` | 15 | 9 | 6 | 0 | 0 |
| `query_detections` | 102 | 88 | 14 | 0 | 0 |
| `query_non_detections` | 0 | 0 | 0 | 0 | 0 |
| `query_forced_photometry` | 14 | 11 | 3 | 0 | 0 |
| `query_lightcurve` populated delegated branches | 116 | 99 | 17 | 116 | 0 |
| `query_probabilities` | 5 | 4 | 1 | 0 | 0 |

## Semantic audit boundary

The audit covers the captured core object, detection, forced-photometry, light-curve, and classification payloads. `query_objects` is classification-bearing: one OID can occur in multiple rows because separate classifiers contribute selected results. Each captured rank-1 result remains an independent `classification@{producer}:alerce` record, with the classifier/model as producer and ALeRCE as channel. The row `oid` is also emitted as a minimal `summary@lsst:alerce` so the classifier result retains its object association through the shared internal payload key/index. Repeated same-OID rows can therefore produce duplicate minimal summaries; generic summary deduplication is intentionally outside this corrective patch. The remaining repeated object-statistic columns stay intentionally unmapped rather than duplicating the full summary for every classifier row. Full probability rows remain assessments rather than synthesized winners.

No authoritative active payload is claimed for unsupported `query_magstats` or `query_features`, for a non-empty non-detection row, or for uncaptured `query_feature`, classifier/class vocabulary, stamp, AVRO, or catsHTM methods.
