# Broker registry mapping refactor: first pass

The repository did not previously contain broker registry material. This pass
therefore establishes the split registry and intentionally limits concrete
mappings to fields represented by the feature catalog. It does not claim that
the small mapped set exhausts each broker's payload.

## Coverage summary

| Broker/origin | Concrete mapped fields | Unmapped-log entries |
|---|---:|---:|
| Fink/ZTF | 3 | 0 |
| Fink/LSST | 3 | 0 |
| ALeRCE/ZTF | 16 | 2 |
| ALeRCE/LSST | 16 | 2 |
| ANTARES/ZTF | 9 | 2 |
| ANTARES/LSST | 9 | 2 |

The zero Fink counts mean no additional raw payload inventory was available in
the repository, not that every Fink field has been semantically mapped.

## Unsupported endpoints

* ALeRCE/LSST: `query_magstats`, `query_features`, and `query_classifiers` are
  retained as `known_unsupported` operations.
* ANTARES/ZTF and ANTARES/LSST: `streaming_client` is retained but disabled
  because the current surface is a placeholder.

## Declared-only and sampled-empty sources

* ALeRCE magstats, features, and classifier metadata sources are declared only;
  the LSST variants link to unsupported endpoints.
* ALeRCE/LSST non-detections are declared only and marked
  `empty_in_sampling`. Their generated semantic fields are inactive.
* ANTARES locus, lazy alert, and lazy lightcurve payload shapes are declared
  from the client object model.

## Dynamic/raw extensions

Only ANTARES `Locus.properties` and `Alert.properties` use dynamic raw
extensions. Each occurrence is explicitly recorded in `unmapped_fields.yaml`.
Fink and ALeRCE have no dynamic fallback mappings.

## Catalog gaps for review

ALeRCE's `dmdt_first` has no exact semantic path. The arbitrary keys inside
ANTARES property dictionaries need survey-specific review before promotion to
stable catalog paths. A future payload-inventory pass should also enumerate and
log all fields from representative Fink and ALeRCE responses.

