# Authoritative Fink/LSST API capture

This directory freezes the raw evidence captured at **2026-08-12T15:54:10Z** for Rubin `diaObjectId=170587117485817955`. The requests targeted the Fink LSST REST API (`https://api.lsst.fink-portal.org`) and all returned HTTP 200.

| Fixture | GET path and query parameters | Rows | Projection |
|---|---|---:|---|
| `objects.json` | `/api/v1/objects?diaObjectId=170587117485817955&output-format=json` | 1 | None (all columns) |
| `sources.json` | `/api/v1/sources?diaObjectId=170587117485817955&output-format=json` | 16 | None (all columns) |
| `fp.json` | `/api/v1/fp?diaObjectId=170587117485817955&output-format=json` | 20 | None (all columns) |
| `conesearch.json` | `/api/v1/conesearch?ra=62.45763123249455&dec=-48.481492749718534&radius=1&n=100&columns=r:diaSourceId,r:diaObjectId,r:midpointMjdTai,r:ra,r:dec,r:band,r:psfFlux,r:psfFluxErr,r:isNegative&output-format=json` | 1 | Nine explicit Rubin fields requested; the returned payload has those nine fields plus `v:separation_degree` |

The actual capture command is the authoritative source for the cone-request parameters shown in the table. The cone center was RA `62.45763123249455` degrees, Dec `-48.481492749718534` degrees, with `n=100`; `radius=1` is the request radius in arcseconds. The requested `columns` projection contained nine explicit Rubin fields and did not include `v:separation_degree`. Fink additionally returned `v:separation_degree`, so the response has ten fields. That additional field is the measured result-to-search-center separation, expressed in degrees. Header files beside each response preserve the HTTP status and response metadata.

## Immutable JSON checksums

```text
66106181ca8f8d3d16cd83f5bcdcb3afb296509fdcae7cf9f829c6cdfac8f785  objects.json
bddb4675604090312b7283254ea32980986f3098222653b75bb9809c160d939a  sources.json
9eef7a54465ea4f07ee40b033a8cb1eb1c4c37d82a124c72bf699c49f327bb55  fp.json
eb06630fea13ef5fb4ed8088ad2f3c0f3fadff0532e468826063ec4dd41d8725  conesearch.json
```
