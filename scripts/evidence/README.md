# Broker evidence capture scripts

These entrypoints acquire raw broker evidence; `tests/fixtures/...` stores frozen,
audited evidence. Captures default to timestamped directories under `/tmp`. Passing a
fixture directory is an explicit user action, and every script refuses to overwrite a
non-empty directory. Raw captures are observations, not semantic truth until audited.
Credentials are used only for transport and are never persisted.

Capture JSON preserves non-finite Python floats with explicit capture-only tags:
`{"__capture_float__": "nan"}`, `{"__capture_float__": "+inf"}`, and
`{"__capture_float__": "-inf"}`. These tags retain provider/client evidence and are
serialization metadata, not semantic normalization; Python `None` remains JSON `null`.

| Broker | ZTF | LSST | Transport |
| --- | --- | --- | --- |
| ALeRCE | [`capture_alerce_ztf.py`](capture_alerce_ztf.py) | [`capture_alerce_lsst.py`](capture_alerce_lsst.py) | Python client |
| ANTARES | [`capture_antares_ztf.py`](capture_antares_ztf.py) | [`capture_antares_lsst.py`](capture_antares_lsst.py) | Python client |
| Fink | [`capture_fink_ztf.sh`](capture_fink_ztf.sh) | [`capture_fink_lsst.sh`](capture_fink_lsst.sh) | REST |
| Lasair | [`capture_lasair_ztf.sh`](capture_lasair_ztf.sh) | [`capture_lasair_lsst.sh`](capture_lasair_lsst.sh) | authenticated REST |

```bash
./scripts/evidence/capture_fink_ztf.sh
./scripts/evidence/capture_fink_ztf.sh tests/fixtures/fink/ztf
python scripts/evidence/capture_alerce_lsst.py
LASAIR_TOKEN=... LASAIR_LSST_OID=... ./scripts/evidence/capture_lasair_lsst.sh
```

ALeRCE and ANTARES require their repository-supported clients. Lasair requires
`LASAIR_TOKEN`; LSST also requires `LASAIR_LSST_OID` because repository Lasair/LSST
fixtures do not establish an authoritative live default.
