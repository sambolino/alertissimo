# Lasair/LSST authoritative evidence

The dated `capture_20260813T140948Z/` directory is the authenticated authoritative Lasair/LSST REST capture used by semantic-registry regressions.

- diaObjectId: `313761042336317573`
- capture date: 2026-08-13
- the contextual object reports `lasairData.nDiaSources=259`; its returned history contains 245 `diaSourcesList` rows and 345 `diaForcedSourcesList` rows; the raw object carries `diaObject.nDiaSources=259`
- singular object, cone, query, Sherlock object, and Sherlock position surfaces returned HTTP 200
- `/api/objects/`, `/api/lightcurves/`, and `/api/sherlock/objects/` returned HTTP 404 and are not registered as LSST endpoints
- Sherlock lite/full and cone all/nearest/count shapes are preserved

Older top-level JSON files predate the authenticated capture and remain legacy/synthetic fixtures. New authoritative checks use the dated capture.
