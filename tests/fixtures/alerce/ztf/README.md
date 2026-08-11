# Authoritative ALeRCE/ZTF response fixtures

These files preserve complete JSON response values returned on **2026-08-11** by the
official Python package `alerce` **2.3.1**, using `alerce.core.Alerce`,
`survey="ztf"`, and `format="json"`. For this client release, the high-level ZTF
methods intentionally route through the package's legacy ZTF client. These are Python
client responses, not direct REST captures or schema-generated examples.

`query_objects.json` and `query_object.json` were captured manually during the same
2.3.1 investigation. The remaining calls are recorded by the automated second capture
in `capture_rest_manifest.json`; that filename is historical and does not mean the
fixtures bypassed the Python client. No timestamp is asserted for the two manual calls
because none was recorded.

| endpoint | fixture | query/object | observed shape or row count |
|---|---|---|---:|
| `query_objects` | `query_objects.json` | explicit OIDs `ZTF18abbuksn`, `ZTF21aaeyldq`, `ZTF17aaaaaak`, `ZTF17aaaaaal` | wrapper dictionary; 4 `items` |
| `query_object` | `query_object.json` | `ZTF18abbuksn` | object dictionary |
| `query_detections` | `query_detections.json` | `ZTF18abbuksn` | 1,044 rows |
| `query_non_detections` | `query_non_detections.json` | `ZTF18abbuksn` | 319 rows |
| `query_forced_photometry` | `query_forced_photometry.json` | `ZTF18abbuksn` | 286 rows |
| `query_lightcurve` | `query_lightcurve.json` | `ZTF18abbuksn` | 1,044 detections and 319 non-detections |
| `query_probabilities` | `query_probabilities.json` | `ZTF18abbuksn` | 344 rows |
| `query_magstats` | `query_magstats.json` | `ZTF18abbuksn` | 2 rows |
| `query_features` | `query_features.json` | `ZTF18abbuksn` | 3,290 rows |

The captured `query_lightcurve` has only `detections` and `non_detections`; forced
photometry is returned by the separate `query_forced_photometry` method. The fixtures
retain all nulls and serialized types (including string-valued `ndethist`) unchanged.

The capture utility writes `capture_manifest.json` for a new run. Review that manifest
and the raw bytes before replacing any evidence here:

```console
python tools/capture_alerce_ztf_payloads.py tests/fixtures/alerce/ztf
```

Registry entries for uncaptured methods such as `query_feature`, classifier/class
listing, stamps, AVRO, and catsHTM are not made authoritative by this fixture set.
