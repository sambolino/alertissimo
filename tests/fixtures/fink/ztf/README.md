# Authoritative Fink/ZTF API fixtures

These immutable responses were captured on **2026-08-12T18:58:35Z** from
`https://api.ztf.fink-portal.org` by `scripts/evidence/capture_fink_ztf.sh`.
The primary object is `ZTF21abfmbix`. The request JSON, response headers, capture
metadata, inventory, and SHA-256 manifest are retained beside every response.

## Response inventory

| Response | Rows | Purpose |
| --- | ---: | --- |
| `objects_core.json` | 14 | Object history with `withupperlim=false` |
| `objects_withupperlim.json` | 33 | Full history: 14 `valid`, 19 `upperlim` |
| `conesearch.json` | 1 | Cone response for radius 5 arcsec and `n=1000` |
| `latests.json` | 10 | Latest Early SN Ia candidates |
| `anomaly.json` | 10 | Anomaly stream |
| `sso_core.json` | 327 | SSO 8467 (`Benoitcarry`) |
| `statistics_day.json` | 1 | Statistics query `date=20211103`, `columns=*` |
| `resolver_tns.json` | 1 | Reverse TNS resolver shape |
| `resolver_simbad.json` | 1 | SIMBAD resolver shape |
| `resolver_ssodnet.json` | 4 | SSODNet resolver shape |

Fink applies `n` before its exact angular cone filter, so a cone request can
return fewer than `n` rows. The three resolver captures intentionally document
three distinct response schemas rather than treating them as interchangeable.
`method_probe.txt` records successful GET transport probes for objects and cone
search.

Verify that no frozen fixture bytes changed:

```bash
(
  cd tests/fixtures/fink/ztf
  sha256sum -c SHA256SUMS.txt
)
```
