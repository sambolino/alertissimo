# Broker mapping refactor report

## First-pass coverage

| Broker/origin | Concrete fields | Unmapped/raw-extension entries |
|---|---:|---:|
| Fink/ZTF | 3 | 0 |
| Fink/LSST | 3 | 0 |
| ALeRCE/ZTF | 7 | 1 |
| ALeRCE/LSST | 7 | 1 |
| ANTARES/ZTF | 5 | 2 |
| ANTARES/LSST | 5 | 2 |

The concrete set is deliberately conservative. Previously documented fields without an exact,
reviewed catalog match remain candidates for subsequent passes rather than being assigned a new
semantic branch.

## Unsupported endpoints

ALeRCE/LSST `query_magstats`, `query_features`, and `query_classifiers` are retained as
`known_unsupported`. ANTARES `streaming_client` is retained but disabled because the current
client surface is a placeholder.

## Declared-only sources

ALeRCE/LSST magstats is declared-only and unsupported. Non-detections is declared-only and
inactive because sampling returned an empty result. These sources cannot create active generated
capabilities.

## Dynamic/raw extension usage

Only ANTARES `Locus.properties` and `Alert.properties` use dynamic raw extensions. Every such
extension is also recorded in `unmapped_fields.yaml`.

## Catalog gaps for review

Magnitude-rate/magstats attributes need explicit catalog review. Broker-specific payload fields
removed from the confident first-pass mapping set should be audited against the ordered semantic
DSL before they are restored; no simplified replacement catalog was introduced.
