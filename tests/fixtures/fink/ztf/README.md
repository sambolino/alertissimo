# Authoritative Fink/ZTF API evidence (2026-08-12)

This directory is a byte-frozen capture of the public Fink/ZTF API at
`https://api.ztf.fink-portal.org`, acquired at **2026-08-12T18:58:35Z** by
`./scripts/evidence/capture_fink_ztf.sh`. The primary object is
`ZTF21abfmbix`. `capture_metadata.txt`, the `*.request.json` files, response
headers, and `capture_script.sha256` preserve the acquisition context.

## Payload inventory

| Response | Rows | Union columns | Query context |
|---|---:|---:|---|
| `objects_core.json` | 14 | 136 | ordinary history; `withupperlim=false`, `withcutouts=false` |
| `objects_withupperlim.json` | 33 | 137 | 14 `valid` plus 19 `upperlim` rows |
| `conesearch.json` | 1 | 15 | RA 193.8217409 deg, Dec 2.8973184 deg, radius 5 arcsec, `n=1000` |
| `latests.json` | 10 | 57 | Early SN Ia candidates, 2021-11-01 through 2021-12-01 |
| `anomaly.json` | 10 | 142 | historical interval 2023-01-25 |
| `sso_core.json` | 327 | 88 | object `8467`; ephemerides, residuals, and cutouts disabled |
| `resolver_tns.json` | 1 | 7 | TNS reverse lookup of `ZTF23aaaahln` |
| `resolver_simbad.json` | 1 | 11 | SIMBAD lookup of `Markarian 2` |
| `resolver_ssodnet.json` | 4 | 3 | SSODNet lookup of `624188` |
| `statistics_day.json` | 1 | 131 | stream statistics for `20211103` |

The three resolver captures intentionally have different schemas and must not
be treated as one homogeneous catalog response. The exact request bodies are
stored beside each response.

Both `/api/v1/objects` and `/api/v1/conesearch` returned HTTP 200 to the frozen
GET method probes (`method_probe.txt`). JSON POST was used by the capture
script; this does not imply that the endpoint contract is POST-only.

For the same cone center and 5-arcsec radius, `n=100` returned no rows while
`n=1000` returned the exact central object. Fink applies `n` to the HBase scan
before its final exact angular filter, so `n` is not merely a returned-row cap.
The authoritative row is `ZTF21abfmbix`, candid
`1642249732315015013`, with `v:separation_degree=0.0`.

## Integrity verification

Run from this directory:

```bash
sha256sum -c SHA256SUMS.txt
```

The checksum manifest covers the ten authoritative JSON responses. Do not
rewrite or reformat those responses; this README is explanatory provenance,
not a replacement for the frozen bytes or executable tests.
