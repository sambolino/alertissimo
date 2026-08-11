# ALeRCE/ZTF response fixtures

No response fixture is committed yet. Repository history contained capture utilities and
schema-derived audit material, but no captured response bytes. On 2026-08-11, installing
the official client was blocked by the environment's package-network proxy (HTTP 403),
so schema-generated or synthetic dictionaries have deliberately **not** been presented
as authoritative payload evidence.

Run `python tools/capture_alerce_ztf_payloads.py tests/fixtures/alerce/ztf` in a normal
networked environment with the official `alerce` package installed. Review the resulting
manifest before committing it; a successful manifest records each call and its query.

| endpoint | fixture | status | source | object/query | capture date | sampling notes |
|---|---|---|---|---|---|---|
| query_object | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_detections | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_non_detections | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_forced_photometry | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_lightcurve | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_probabilities | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_objects | — | provisional | runtime capture unavailable; no payload bytes | first non-empty discovery query | 2026-08-11 | no fixture invented |
| query_magstats | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
| query_features | — | provisional | runtime capture unavailable; no payload bytes | discovery object | 2026-08-11 | no fixture invented |
