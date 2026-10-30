# Reference workflow input inventory

Inventory for `feat/integration-07a-reference-material`, based on integration
`b34eb1d` / PR #321. Its manual DSL checkpoint
[41041721319](https://github.com/sambolino/alertissimo/actions/runs/41041721319)
passed. The final integration guide should link this inventory, not duplicate a
second source of material-availability claims.

The reference application is
[nucleuswatch at `f0b4ee7`](https://github.com/bibinthomas123/nucleuswatch/tree/f0b4ee7fff4db6faf508d01e5b8b0311f0e3d52d).
Read-only inspection covered `src/nucleuswatch/recipes.py`,
`brokers/fink.py`, `alertissimo_bridge.py`, and `docs/alertissimo.md` at that
revision. This is an input audit, not a claim of identical candidate populations,
scientific classifications or complete compatibility with that bridge.

## Required ZTF material

Statuses: **Available** is already retained through the named endpoint/mapping;
**Implemented** is added in this series; **External** belongs to the consuming
application; **Deferred** names an unimplemented or unproven contract. Availability
means a field can be retained when returned, not that every row contains it.

| Input and reference use | Status | Alertissimo evidence and access | Limits |
| --- | --- | --- | --- |
| Object ID and sky position | Available | Fink `objects` and `latests`: `summary@ztf:fink.identity.object_id`, detection `position.ra` / `position.dec`; candidate ownership is `(origin, object_id)` | Select the candidate Portfolio before reading records; an explicit ID must not relabel several objects |
| Observation time | Available | Fink `i:jd` becomes `detection@ztf:fink.time.mjd` | JD-to-MJD is a numeric representation change; preserve the survey time convention; Rubin TAI is not ZTF UTC |
| Magnitude, uncertainty and band | Available | Fink `i:magpsf`, `i:sigmapsf`, `i:fid` become `photometry.{filter}.psf.mag`, `.error` and the dynamic filter context | Keep ordinary detections, upper limits and forced photometry distinct; missing data are not zero |
| Detection identity | Available | Fink `i:candid` becomes `identity.source_id`; execution/payload/index provenance identifies its row | A detection ID is not an object ID; preserve exact integer IDs |
| Real/bogus quality and model version | Available | `quality.real_bogus`, `quality.real_bogus.version` where mapped/returned | A pipeline version is not a replacement for a classifier-specific version |
| Fink class and science scores | Available | `classification@fink.best.class` and named assessments from `objects`/`latests` | These are alert-dependent assertions; keep their source row, do not assume the first record is current |
| Classifier identity, version, label, probability and rank | Implemented in PR 01; existing mappings | ALeRCE `query_probabilities`: `classification@{producer}:alerce`, `provenance.producer.name`, `.version`, `assessment.{output}.class`, `.probability`, `.rank` | Do not fabricate a missing version/probability; classifier names and channels are separate qualifiers |
| Pan-STARRS rank-one association distance | Available | Fink `objects`, `latests`, `anomaly`, `sso`: `crossmatch@panstarrs:fink.separation.total` from `i:distpsnr1` | Arcseconds; it is the associated catalogue source, not a measured host-centre offset |
| Pan-STARRS star/galaxy score | Available | Same endpoints: `classification.assessment.star_galaxy.score` from `i:sgscore1` in the Pan-STARRS record | Keep the association and score together; unavailable score does not mean galaxy |
| Nearest reference-source image distance | Implemented in 07a | Fink `i:distnr` becomes `detection@ztf:fink.reference_image.nearest_source.pixel_distance` | Pixels, with no angular conversion; a nearby reference source is not automatically a host nucleus |
| Reported detection-history count | Available | Fink `i:ndethist` becomes `summary@ztf:fink.detection_count` | Each alert retains its historical snapshot; the first captured row reports 17, earlier rows report lower counts, and the loaded history has 14 ordinary detections |
| Historical coverage count | Available | Fink `objects`/`anomaly`: `coverage_count` from `i:ncovhist` | Distinct from detection count and loaded upper-limit count |
| Positive subtraction | Available | Fink `objects`, `latests`, `anomaly`, `sso`: `image_metrics.is_positive` from `i:isdiffpos` | Existing value mapping preserves negative subtraction as `false`; this does not remove its measurement |
| First/last reported historical detection times | Available | Fink `i:jdstarthist` / `i:jdendhist` become summary `time.first_mjd` / `time.last_mjd` | These follow ZTF's historical-count selection; no assumption that a broker's loaded history is exhaustive |
| SIMBAD, TNS and Sherlock context | Available where returned | Fink `crossmatch@simbad:fink` / `crossmatch@tns:fink`; Lasair `classification@sherlock:lasair` and `classification@tns:lasair` from object/objects, with dedicated Sherlock recipes where admitted | Unknown/empty values remain absent under existing transforms; a TNS class is not its object name; do not replace classification with catalogue membership |
| Classification and time discovery | Implemented with explicit limits | Earlier Fink class/time branches admit `SN candidate` and `Early SN Ia candidate`; ALeRCE/Lasair/ANTARES have their separately documented contracts | Saturated Fink responses fail explicitly; its full reference stream list and global object latest are not thereby supported |
| Image cutouts | Deferred to 07b audit | Inspect Fink `cutouts` response modes against existing `data_product` before activation | This branch adds no product recipe or binary handling |
| Flare onset, age/new-known policy, brightest passing alert and cross-broker consensus | External | Nucleuswatch `recipes.py`, `core.py`, taxonomy and scoring | Broker evidence supports these calculations; Alertissimo does not adopt their scientific policies |
| Legacy Surveys host TAP, TDE model, Zooniverse, notifications and scheduling | External | Nucleuswatch host/model/publishing functions | No extra endpoint or workflow layer is introduced here |
| Additional Rubin discovery and classification joins | Deferred pending consultation | End-of-series discussion specified in the integration plan | Do not infer Rubin columns, units, table joins or producer identity from ZTF |

## Endpoint-specific evidence

The immutable Fink capture scope is
[`tests/fixtures/fink/ztf/README.md`](../tests/fixtures/fink/ztf/README.md).
Frozen JSON bytes and manifests are unchanged. Request projections matter:
declaring a possible output is not proof that every projection returns it.

| Endpoint capture | Relevant material actually observed | Important absence or restriction |
| --- | --- | --- |
| `objects_core.json`, 14 rows | ID, coordinates, JD, band, magnitude/error, candid, distnr, PS1 distance/score, historical counts/times, positive flag, science version, classification/scores | Many catalogue context fields can be empty; 14 loaded detections do not replace the reported count of 17 |
| `objects_withupperlim.json`, 33 rows | The same 14 ordinary detections plus 19 upper limits | Upper-limit quality, candid, magnitude and context fields may be absent or sentinel-valued; never count these as 33 ordinary detections |
| `latests.json`, 10 rows | Class-stream alerts with the photometric, PS1, reference-distance, count/time and subtraction inputs | Science version is not present in this capture; this stream supplies alerts, potentially several per object, not globally ranked complete objects |
| `conesearch.json`, one row | Object ID, position, time, magnitude/error, candid, distnr, first historical time | This projection does not supply PS1 distance/score, subtraction sign, historical count, or last history time; use a required subsequent retrieval before relying on those inputs |
| `anomaly.json`, 10 rows | Reference/PS1 context, photometry, historical counts/times, sign and classification | Some catalogue/astrometric fields have their own sentinel rules; anomaly discovery is not the reference SN stream |
| `sso_core.json`, 327 rows | Pixel distance also exists here and uses the same candidate schema | The endpoint groups by SSO identity and is not a stationary-object nuclear search; mapping availability does not activate such a recipe |

The new mapping covers only the five captured Fink candidate payloads that had
`i:distnr` in the unmapped inventory. It does not add a blanket mapping for fields
with the same spelling in another survey, provider or forced-photometry payload.

## Unit contract and data preservation

The primary [ZTF candidate schema](https://zwickytransientfacility.github.io/ztf-avro-alert/schema.html)
defines candidate `distnr` in pixels, while `distpsnr1` is an angular catalogue
distance. `reference_image.nearest_source.pixel_distance` is a small new leaf in
the existing reference-source context, with unit `pixels`. The existing
`separation.total` unit stays `arcsec`. No constant plate scale or automatic
pixel-to-angle conversion is inferred. In particular, the reference application's
comment calling its `distnr_max` threshold arcseconds must not be copied as a
unit guarantee; that application applies the raw numeric threshold.

Zero and negative raw numeric values remain unchanged. A negative sentinel is
not a close association: consumers should require a valid nonnegative distance
before applying a maximum threshold. Null/missing values stay unavailable (null values do not create this leaf), and
raw execution payloads retain their original representation. This branch neither
invents a sentinel conversion nor changes existing positive/negative-subtraction
transforms.

An existing ALeRCE detection mapping uses angular separation for its `distnr`.
Its [REST client documentation](https://alerce.readthedocs.io/en/latest/models/ztf_detection.html)
describes pixels, whereas its [TAP column metadata](https://tap.alerce.online/__system__/dc_tables/show/tableinfo/alerce_tap.ztf_detection)
describes arcseconds. This is the explicitly scheduled 07c unit audit;
neither reinterpret that field nor claim it is a verified angular substitute for
the new Fink pixel field. No ALeRCE mapping is changed by 07a. ZTF's separate
forced-photometry schema also documents a same-named angular field, reinforcing
the need to check the exact payload contract.

## Scientific equivalence and application boundary

The reference `NuclearCuts.passes` applies all cuts to **one raw alert row**,
then keeps the brightest passing alert per object. Candidate filters over a
Portfolio preserve all measurements and are not automatically an equivalent
row selection. A conjunction over one detection selector is correlated to that
detection record; a conjunction involving detection and crossmatch selectors
does not by itself establish their common alert row.

For an exact reference comparison, correlate returned records by existing
`internal_source` execution, payload and row index before applying the combined
cuts. Keep candidate ownership and provenance intact. PR 08 documents application
access to this evidence; PR 09 compares candidates and explains differences.
No new cross-record predicate language or measurement-restriction operation is
introduced in this mapping branch.

The current external bridge also combines records before choosing an object and
assumes the first classification is current. Those consumer assumptions are not
supported contracts. Changes to Bibin's repository remain a proposed follow-up;
this branch does not modify it or introduce its `BrokerResult` into Alertissimo.

## Local handoff

No tests, builds, project imports, applications or provider requests ran here.
Only source/capture inspection, static Python/YAML parsing, whitespace and bundle
verification were performed.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_reference_workflow_material.py \
  tests/test_semantic_model_validation.py \
  tests/test_semantic_paths.py \
  tests/test_mapping_schema.py \
  tests/test_payload_mapping_coverage.py \
  tests/test_fink_ztf_authoritative_payloads.py \
  2>&1 | tee /tmp/alertissimo-integration-07a-tests.log
```

Target the integration branch and squash after these checks pass. The next small
review is 07b, the cutout audit, followed by the small 07c ALeRCE unit audit.
Because 07a changes ontology and mappings, run one manual **Semantic registry**
checkpoint after this material sequence. Keep final full CI and live acceptance
before main; the successful 06e DSL checkpoint is not registry validation of this
new leaf.
