# ALeRCE/ZTF payload evidence

No JSON in this directory is currently claimed as authoritative. On 2026-08-11 the audit searched the repository history and workspace for `alerce_schema_payload_audit_bundle.tar.gz` and saved ALeRCE JSON, but found neither. Installing the official `alerce` client was blocked by the environment's network proxy. Synthetic payloads are deliberately not substituted.

| endpoint | fixture | status | source | object/query | capture date | notes |
|---|---|---|---|---|---|---|
| `query_object` | — | provisional | endpoint metadata only | — | 2026-08-11 | Live capture still required. |
| `query_detections` | — | provisional | endpoint metadata only | — | 2026-08-11 | Live capture still required. |
| `query_non_detections` | — | provisional | endpoint metadata only | — | 2026-08-11 | Live capture still required; runtime cannot inject `limit.upper_limit = true` from endpoint context. |
| `query_forced_photometry` | — | provisional | endpoint metadata only | — | 2026-08-11 | Live capture still required. |
| `query_lightcurve` | — | provisional | endpoint metadata only | — | 2026-08-11 | Nested branches delegate to their branch payload definitions. |
| `query_probabilities` | — | provisional | endpoint metadata only | — | 2026-08-11 | Live capture still required. |

The mapping keeps non-detection rows as `detection@ztf:alerce` and maps their limiting magnitude. Because the current mapping DSL only derives values from raw leaves, it cannot add the context-derived constant `photometry.{filter}.limit.upper_limit = true`. Endpoint and execution provenance therefore remain the only formal runtime distinction until a provider-neutral constant mapping is introduced.
