# Authoritative ANTARES/ZTF client-visible evidence

Captured **2026-08-12** with the official **`antares-client 1.14.0`** for ZTF object `ZTF20aafqubg` / ANTARES locus `ANT2020nb5h6`. These frozen files cover `get_by_ztf_object_id`, `get_by_id`, `search`, `cone_search`, and the rich Locus's lazy `alerts`, `lightcurve`, and `catalog_objects` relationships. Search returned one locus; the 1-arcsec cone returned four. The six non-empty catalog families are AllWISE, 2MASS PSC, Gaia DR3 variability, Bailer-Jones Gaia EDR3 distances, Gaia DR3 source, and the Bright Guide Star Catalog.

The capture contains 316 Alerts: 70 candidates and 246 upper limits. The selected ANTARES lightcurve contains 280 unique Alert IDs (56 candidates and 224 upper limits), all a subset of the Alerts; it omits 36 valid Alerts, so Alert objects—not the lightcurve—are the authoritative observation history. No selection rule is inferred. A supplementary manual probe found 316 `locus.timeseries` rows; that duplicate representation was intentionally not committed.

To serialize client-visible Python values, datetime/Timestamp values became ISO strings, NumPy scalars became Python scalars, NaN/Inf became JSON `null`, and DataFrames became lists of row dictionaries. These are representation-only conversions, distinct from Alertissimo's semantic normalization. Tests assemble the independently frozen core, alerts, and catalogs in memory to mirror an accessed lazy Locus; no fixture claims to be a single raw HTTP response.

## Exact semantic leaf audit

| Evidence branch | Mapped | Intentionally unmapped | Delegated / structural | Unaccounted |
|---|---:|---:|---:|---:|
| rich `get_by_ztf_object_id` composite | 68 | 834 | 712 | 0 |
| `get_by_id` locus core | 4 | 187 | 0 | 0 |
| `search` locus rows | 4 | 186 | 0 | 0 |
| `cone_search` locus rows | 4 | 186 | 0 | 0 |
| Alert rows | 21 | 96 | 0 | 0 |
| 2MASS PSC | 9 | 58 | 0 | 0 |
| AllWISE | 11 | 288 | 0 | 0 |
| Bright Guide Star Catalog | 3 | 58 | 0 | 0 |
| Gaia DR3 source | 14 | 138 | 0 | 0 |
| Gaia DR3 variability | 3 | 3 | 0 | 0 |
| Bailer-Jones EDR3 distances | 3 | 7 | 0 | 0 |
| lightcurve secondary representation | 0 | 14 | 0 | 0 |

The rich audit separately selects the locus core, 316 Alert rows, and each of the six direct-row catalog branches. Lightcurve fields—including ANTARES corrected magnitudes—are explicit secondary-representation debt and do not emit duplicate detections. **Unaccounted leaves: 0.**
