# ALeRCE/ZTF payload evidence register

The worktree and Git object history were searched for `alerce_schema_payload_audit_bundle.tar.gz` and saved responses. The historical collector source and endpoint audit metadata remain, but the response bundle itself was never committed. A fresh collection was attempted on 2026-08-11, but package and public API access were blocked by the execution environment's HTTP proxy. Consequently **there are no authoritative fixtures in this revision**, and no schema- or mapping-derived payload is presented as observed evidence.

| endpoint | fixture | status | source | object/query | captured date | notes |
|---|---|---|---|---|---|---|
| query_objects | — | provisional | historical audit metadata only | default discovery query | — | Exact serialized response unavailable. |
| query_object | — | provisional | historical audit metadata only | `ZTF21aaeyldq` | — | Prior audit records 20 observed leaves; values unavailable. |
| query_detections | — | provisional | historical audit metadata only | `ZTF21aaeyldq` | — | Prior audit records 27 observed leaves; values unavailable. |
| query_non_detections | — | provisional | historical audit metadata only | `ZTF21aaeyldq` | — | Non-empty response was previously observed but not retained. |
| query_forced_photometry | — | provisional | historical audit metadata only | `ZTF17aaaaaak` | — | Large response was previously observed but not retained. |
| query_lightcurve | — | provisional | historical audit metadata only | `ZTF21aaeyldq` | — | Nested response was previously observed but not retained. |
| query_magstats | — | provisional | historical audit metadata only | `ZTF21aaeyldq` | — | Exact rows unavailable. |
| query_probabilities | — | provisional | historical audit metadata only | `ZTF17aaaaaak` | — | Exact classifier rows unavailable. |
| query_features | — | provisional | historical audit metadata only | `ZTF17aaaaaal` | — | Exact feature rows unavailable. |
| query_feature | — | provisional | client contract only | feature selected from `query_features` | — | No successful historical sample recorded. |
| query_classifiers | — | provisional | client contract only | default query | — | Service metadata; exact response unavailable. |
| query_classes | — | provisional | client contract only | classifier-dependent query | — | Service metadata; exact response unavailable. |
| get_stamps | — | provisional | client contract only | object/candid-dependent | — | Binary/array return could not be sampled faithfully. |
| get_avro | — | provisional | client contract only | object-dependent | — | Binary transport return could not be sampled faithfully. |
| catshtm_conesearch | — | provisional | client contract only | catalogue/position-dependent | — | Catalogue producer exists in request context; response unavailable. |
| catshtm_crossmatch | — | provisional | client contract only | catalogue/position-dependent | — | Catalogue producer exists in request context; response unavailable. |
| catshtm_redshift | — | provisional | client contract only | position-dependent | — | Exact response unavailable. |

## Ontology gaps found

| raw concepts | established meaning | current limitation | possible future concept |
|---|---|---|---|
| `query_features` / `query_feature` values | ALeRCE light-curve feature outputs | No instantiable feature portfolio record or stable feature vocabulary. | A first-level derived-feature record with feature name, band, version, and value. |
| forced-photometry correction variants | Raw, corrected, and extended-source-corrected forced measurements | Current forced-photometry container does not formally distinguish all correction states. | Explicit correction method/state subrecords. |
| classifier catalogue/class metadata | Administrative descriptions of available models and classes | These are service metadata, not object classification events. | Broker-service metadata outside the astronomical portfolio. |
| stamp and AVRO bytes | Binary scientific/transport products | Scalar mapping cannot faithfully represent the official client return. | Typed binary data-product transport metadata. |
| CatSHTM request-selected catalogue | External scientific producer supplied in execution context | Mapping files cannot bind request parameters as producer identity without runtime architecture changes. | Provider-neutral execution-context provenance binding. |

These gaps are intentionally semantic debt. `ontology.yaml` is unchanged, no graph edges were added, and no synthetic fixture is used to claim authoritative completeness.
