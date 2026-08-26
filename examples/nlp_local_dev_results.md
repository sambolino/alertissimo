# Local NLP → DSL baseline

- Model: `qwen3:8b`
- Seed: `42`
- Development examples: 15
- Acceptance examples from `nlp_examples.txt` were not used.
- Generated DSL was validated locally and never executed.

| Metric | Passed |
|---|---:|
| Exact DSL | 4/15 |
| Valid DSL | 6/15 |
| Runnable DSL | 5/15 |

## 1 · en

> Find ZTF object ZTF19aabcedf through Antares and return its light curve through Antares.

- exact: yes
- valid: yes
- runnable: yes
- latency: 64.49 s

```dsl
object ZTF19aabcedf from ztf via antares
with lightcurve via antares
```

Expected:

```dsl
object ZTF19aabcedf from ztf via antares
with lightcurve via antares
```

## 2 · en

> Find the latest 3 ZTF objects through ALeRCE within 2 arcseconds of RA 210.25 degrees and Dec -12.5 degrees.

- exact: no
- valid: no
- runnable: no
- latency: 20.15 s

```dsl
objects from ztf via alerce inside (210.25, -12.5, 2arcsec) latest 3
```

Expected:

```dsl
objects from ztf via alerce
inside (210.25, -12.5, 2arcsec)
latest 3
```

## 3 · en

> Look up LSST object 313936986529333309 in Fink and return its light curve from Fink.

- exact: yes
- valid: yes
- runnable: yes
- latency: 20.49 s

```dsl
object 313936986529333309 from lsst via fink
with lightcurve via fink
```

Expected:

```dsl
object 313936986529333309 from lsst via fink
with lightcurve via fink
```

## 4 · en

> Find ZTF object ZTF18abcdefg through Antares and return its crossmatch with the Gaia catalog through Antares.

- exact: yes
- valid: yes
- runnable: yes
- latency: 14.82 s

```dsl
object ZTF18abcdefg from ztf via antares
with crossmatch from gaia via antares
```

Expected:

```dsl
object ZTF18abcdefg from ztf via antares
with crossmatch from gaia via antares
```

## 5 · en

> Retrieve ZTF object ZTF22abcdefg through ALeRCE and return its light curve from ALeRCE.

- exact: no
- valid: yes
- runnable: yes
- latency: 15.64 s

```dsl
object ZTF22abcdefg from ztf via antares
with lightcurve via alerce
```

Expected:

```dsl
object ZTF22abcdefg from ztf via alerce
with lightcurve via alerce
```

## 6 · en

> Search for LSST objects through Lasair within 30 arcseconds of RA 15.75 degrees and Dec 22.1 degrees.

- exact: no
- valid: no
- runnable: no
- latency: 21.26 s

```dsl
object from lsst via lasair
inside (15.75, 22.1, 30arcsec)
```

Expected:

```dsl
objects from lsst via lasair
inside (15.75, 22.1, 30arcsec)
```

## 7 · en

> Use Fink to find ZTF object ZTF18acurdih and return its classification.

- exact: no
- valid: no
- runnable: no
- latency: 14.13 s

```dsl
object ZTF18acurdih from ztf via fink with classification via fink
```

Expected:

```dsl
object ZTF18acurdih from ztf via fink
with classification via fink
```

## 8 · en

> Get the light curve of ZTF object ZTF20acpwljl from Lasair.

- exact: no
- valid: yes
- runnable: no
- latency: 14.26 s

```dsl
object ZTF20acpwljl from lasair via antares
with lightcurve via antares
```

Expected:

```dsl
object ZTF20acpwljl from ztf via lasair
with lightcurve via lasair
```

## 9 · en

> Retrieve the light curve for LSST object 170587117485817955 through ALeRCE.

- exact: no
- valid: no
- runnable: no
- latency: 22.29 s

```dsl
object 170587117485817955 from lsst via alerce with lightcurve
```

Expected:

```dsl
object 170587117485817955 from lsst via alerce
with lightcurve via alerce
```

## 10 · en

> Find ZTF object ZTF20aafqubg through Antares and return both its Gaia crossmatch and its light curve.

- exact: yes
- valid: yes
- runnable: yes
- latency: 23.28 s

```dsl
object ZTF20aafqubg from ztf via antares
with crossmatch from gaia via antares
with lightcurve via antares
```

Expected:

```dsl
object ZTF20aafqubg from ztf via antares
with crossmatch from gaia via antares
with lightcurve via antares
```

## 11 · en

> Through ALeRCE, find the latest 5 objects from either LSST or ZTF within 5 arcseconds of RA 124.87996 degrees and Dec -6.02050 degrees.

- exact: no
- valid: no
- runnable: no
- latency: 25.49 s

```dsl
objects from lsst or ztf via alerce inside (124.87996, -6.0205, 5arcsec) latest 5
```

Expected:

```dsl
objects from lsst, ztf via alerce
inside (124.87996, -6.02050, 5arcsec)
latest 5
```

## 12 · en

> Use ALeRCE to retrieve ZTF object ZTF18abbuksn together with its classification and light curve.

- exact: no
- valid: no
- runnable: no
- latency: 16.94 s

```dsl
object ZTF18abbuksn from ztf via alerce with classification via alerce with lightcurve via antares
```

Expected:

```dsl
object ZTF18abbuksn from ztf via alerce
with classification via alerce
with lightcurve via alerce
```

## 13 · en

> Look up ZTF objects ZTF18acurdih and ZTF21abfmbix in Fink and return a light curve for each object.

- exact: no
- valid: no
- runnable: no
- latency: 20.38 s

```dsl
object ZTF18acurdih from ztf via fink with lightcurve
object ZTF21abfmbix from ztf via fink with lightcurve
```

Expected:

```dsl
objects ZTF18acurdih, ZTF21abfmbix from ztf via fink
with lightcurve via fink
```

## 14 · en

> Find the latest 10 ZTF objects reported through Fink during the last 7 days.

- exact: no
- valid: no
- runnable: no
- latency: 16.78 s

```dsl
object from ztf via fink latest 10 inside (0, 0, 10000arcsec)
```

Expected:

```dsl
objects from ztf via fink
within 7d
latest 10
```

## 15 · en

> Search Fink for ZTF objects within 5 arcseconds of RA 124.87996 degrees and Dec -6.02050 degrees, then return their light curves from both Fink and Lasair.

- exact: no
- valid: no
- runnable: no
- latency: 30.14 s

```dsl
object ZTF20abc from ztf via fink
inside (124.87996, -6.02050, 5arcsec)
with lightcurve via fink
with lightcurve via lasair
```

Expected:

```dsl
objects from ztf via fink
inside (124.87996, -6.02050, 5arcsec)
with lightcurve via fink
with lightcurve via lasair
```
