# ALeRCE reference-source distance units

Branch `fix/integration-07c-alerce-distance-units`, based on integration
`f8e0909` / PR #324. Target `integration/discovery-completion`.

The intermediate ontology change is the baseline: concrete records are named
`measurement`; `enrichment` is abstract and expands to admitted concrete Gets.
This branch reuses those names and the existing pixel-distance leaf. It adds no
ontology containers, inheritance rules, DSL aliases or architecture layers.

## Corrected mapping

The previous mapping assigned all three ALeRCE ZTF `distnr` inputs to the angular
`separation.total` field. Their documented client response contracts differ:

| Client payload | Semantic field on `measurement@ztf:alerce` | Unit | Effect |
| --- | --- | --- | --- |
| `query_detections#distnr` | `reference_image.nearest_source.pixel_distance` | pixels | Move out of the angular field |
| `query_lightcurve.detections#distnr` | `reference_image.nearest_source.pixel_distance` | pixels | Same correction for the lightcurve's detection branch |
| `query_forced_photometry#distnr` | `reference_image.nearest_source.separation.total` | arcsec | Retain the existing angular mapping |

No raw number is rescaled. Missing fields stay absent; explicit nulls remain
unavailable, and zero/negative values are preserved. No sentinel policy or
conversion between pixels and arcseconds is invented. All original measurement
content, producer/channel qualifiers and source provenance remain intact.

Consumers filtering ordinary ALeRCE detections must now use the pixel field.
An angular reference-distance predicate no longer matches an ordinary detection's
pixel value; angular values from forced photometry remain available in their own
measurement records. No backwards alias can make the two units equivalent.
Existing feature IDs and the angular semantic leaf are retained.

## Primary-source audit

The frozen client captures identify ALeRCE **2.3.1**. Read-only inspection used
official [`alercebroker/alerce_client` tag `v2.3.1`](https://github.com/alercebroker/alerce_client/tree/44294b14e7c14e17a4fa4692b0d4dbe4b1838813),
commit `44294b14e7c14e17a4fa4692b0d4dbe4b1838813`:

- `docs/source/models/detection.rst` documents detection `distnr` in pixels.
- `docs/source/models/forced_photometry.rst` documents its different `distnr` in
  arcseconds. Both current ZTF-specific response pages retain this distinction.
- `alerce/common_search.py` routes explicit `survey="ztf"` to the legacy ZTF
  client, matching this registry and its authoritative captures.
- `alerce/default_config.json` routes detections/lightcurve to `/ztf/v1/objects/…`
  and forced photometry to the distinct `/v2/lightcurve/forced-photometry/…` path.
- `alerce/ztf_search.py` and `alerce/utils.py` return JSON without distance scaling;
  the forced-photometry JSON branch flattens extra fields without unit conversion.

Public references:
[detection response](https://alerce.readthedocs.io/en/latest/models/detection.html),
[forced-photometry response](https://alerce.readthedocs.io/en/latest/models/ztf_forced_photometry.html),
and [ZTF candidate/forced-history schemas](https://zwickytransientfacility.github.io/ztf-avro-alert/schema.html).
The upstream candidate and forced-history schemas likewise distinguish the units.

ALeRCE's separate [TAP detection metadata](https://tap.alerce.online/__system__/dc_tables/show/tableinfo/alerce_tap.ztf_detection)
labels its column arcseconds. It is a different exposed contract and is not an
Alertissimo endpoint in this branch. This correction follows the actual registered
client methods and their response documentation; it does not resolve that upstream
metadata discrepancy or certify TAP-to-client numeric equivalence. Numeric
similarity between captures is not evidence of a unit conversion. No TAP query or
live broker request was made, and no upstream issue/message was sent.

## Recorded and family regression evidence

The unchanged captures contain `distnr` in all 1,044 detection rows, the matching
1,044 lightcurve detection rows, and 286 forced-photometry rows. Their first values
are respectively `0.17920029`, `0.17920029` and `0.18499428033828735`; tests require
those raw values to appear only under their documented unit-specific field.
No fixture bytes or unmapped exclusions change.

The new offline regression also executes `with enrichment` through the current
public DSL using recorded subsets and a fake Python transport. Family expansion
retains ordinary pixel evidence. Its lightcurve Get inherits candidate flow with
unknown target cardinality, so the existing policy omits the optional singular
forced-photometry call even when the preceding lookup names one object. A second
case uses an explicitly targeted singleton `GetLightcurveStep` and verifies both
ordinary pixel and forced-photometry angular evidence in their own measurements.
Both cases check offline normalization and absence of supplementary failures.
Neither claims completeness for those deliberately small replay subsets.

The follow-up fixture correction changes no production planning or mappings.

## Local handoff and shared checkpoint

No project imports, tests, builds, applications or provider calls ran here.
Static AST/YAML parsing, source/capture inspection, whitespace and bundle checks
accompany this branch. The registry workflow now installs the existing pinned
Lark dependency required by its public-API replay tests, including the 07b cutout
regressions.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_alerce_reference_distance_units.py \
  tests/test_alerce_ztf_authoritative_payloads.py \
  tests/test_alerce_registry_architecture.py \
  tests/test_reference_workflow_material.py \
  tests/test_dsl_enrichment_family.py \
  tests/test_semantic_families.py \
  tests/test_semantic_paths.py \
  tests/test_mapping_schema.py \
  2>&1 | tee /tmp/alertissimo-integration-07c-tests.log
```

After local success and squash, run one manual Semantic registry checkpoint on the
updated integration branch. Also run DSL once: the last recorded DSL checkpoint
was `b34eb1d`, before PR #324 changed record names, family membership and lowering.

```bash
gh workflow run semantic-registry.yml --ref integration/discovery-completion
gh workflow run dsl.yml --ref integration/discovery-completion
gh run list --branch integration/discovery-completion --limit 5
```

Watch the newly dispatched runs, not reruns of older SHAs. Result access (08) and
reference acceptance/support matrix (09) remain next. Classification joins and
additional Rubin discovery remain the agreed end-of-series consultation items.
