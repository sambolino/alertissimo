# C3a — ANTARES ZTF catalogue classification evidence

Branch: `feat/classification-antares-ztf-context`.
Base: `2b1bcf4`, the merged Lasair classification repair, on integration.
Target: `integration/discovery-completion`. Keep #329 draft.

## Mapped evidence

The frozen ANTARES/ZTF catalogue rows contain five established classification
fields that were still debt. Map them using the same paths already present for
ANTARES/LSST, under the existing matched-object records:

| Raw field | Record | Relative semantic field |
| --- | --- | --- |
| `classprob_dsc_combmod_galaxy` | `crossmatch@gaia:antares` | `classification.assessment.gaia_dsc_galaxy.probability` |
| `classprob_dsc_combmod_quasar` | `crossmatch@gaia:antares` | `classification.assessment.gaia_dsc_quasar.probability` |
| `classprob_dsc_combmod_star` | `crossmatch@gaia:antares` | `classification.assessment.gaia_dsc_star.probability` |
| `class` | `crossmatch@gaia_variability:antares` | `classification.assessment.gaia_variability.class` |
| `classifier` | `crossmatch@gaia_variability:antares` | `classification.assessment.gaia_variability.method` |

These describe matched catalogue sources. They do not classify the transient
candidate or establish a host association. Keep catalogue source IDs, exact raw
values and execution/payload-row provenance. Do not create a top-level
`classification@...` record, select a winning class, translate the raw variability
label, infer a model version or renormalize the three probabilities.

The captured variability values are `RS` and `nTransits:5+`; preserve both verbatim.
The separate `solid` field stays unmapped. The Gaia DSC values refer specifically
to Combmod; its native class definitions must not be equated automatically with
other brokers' labels or binary scores. Five classes exist in the upstream DSC
model, while these ANTARES rows expose only the three mapped fields.

## Primary definitions consulted

- [ESA Gaia DR3 gaia_source](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_main_source_catalogue/ssec_dm_gaia_source.html): definitions of the three DSC-Combmod probability columns.
- [ESA Gaia DR3 DSC outputs](https://gea.esac.esa.int/archive/documentation/GDR3/Data_analysis/chap_cu8par/sec_cu8par_apsis/ssec_cu8par_apsis_dsc.html): model/class distinctions and the five-class Combmod output.
- [ESA Gaia DR3 variability classifier results](https://gea.esac.esa.int/archive/documentation/GDR3/Gaia_archive/chap_datamodel/sec_dm_variability_tables/ssec_dm_vari_classifier_result.html): classification labels and classifier-name metadata. The provider's field names/spelling remain those in the capture.
- [ANTARES FAQ](https://antares.noirlab.edu/faq): tags represent filter membership/output streams. That role does not establish a physical class or probability.

The semantic placement follows Alertissimo's existing ontology rule: a nested
classification on a crossmatch describes the matched object. No new ontology
containers, fields, architecture layers, adapters or endpoint routes are added.

## Retrieval and current limits

Use the existing targeted crossmatch acquisition and explicit catalogue predicate:

```text
object ZTF20aafqubg from ztf via antares
with crossmatch from gaia via antares
filter crossmatch@gaia:antares.classification.assessment.gaia_dsc_star.probability >= 0.99
```

This named fixture satisfies that threshold. `filter` is shown as a later
refinement; it does not redefine the planned request-wide C4 `with/where` contract.
Candidate selection retains the full surviving Portfolio and its measurements.

The inspected ZTF locus also contains `anomaly_score`, `anomaly_type` and
`anomaly_mask` (the capture includes `anomaly_mask: Fail`). A raw name/value alone
does not verify the producing method, score meaning or mask validity rule, so
those outputs remain explicit debt. Tags are not silently converted to class
assertions. This is an evidence limit, not a claim that the live service cannot
provide classification through other filters or data products.

Candidate-level `with classification via antares` remains unsupported on the
current registered contract. No new GetClassification recipe or classification
search is activated. The existing LSST Gaia fields already use these paths and
are left unchanged; this PR does not claim new LSST or live acceptance.

## Audit and local checks

Remove only these five raw references from semantic debt. The rich ZTF audit
becomes 90 mapped, 812 intentionally unmapped, 712 delegated/structural and zero
unaccounted leaves. Historical README counts remain documented alongside the
updated counts. Frozen fixture bytes are unchanged.

Preparation used static AST/YAML parsing, source/capture inspection, primary
documentation review, whitespace and bundle checks. No project imports, tests,
builds, applications or live broker requests ran here. Documentation lookups are
not provider acceptance requests.

```bash
set -o pipefail
PYTHONPATH=. python -m pytest -q \
  tests/test_antares_ztf_classification_context.py \
  tests/test_antares_ztf_authoritative_payloads.py \
  tests/test_antares_lsst_authoritative_payloads.py \
  tests/test_mapping_schema.py \
  tests/test_semantic_record_builder.py \
  tests/test_semantic_model_validation.py \
  tests/test_orchestration_crossmatch_recipes.py \
  tests/test_orchestration_classification_recipes.py \
  tests/test_dsl_classification_recipes.py \
  tests/test_antares_registry_architecture.py \
  tests/test_api_continuation.py \
  2>&1 | tee /tmp/alertissimo-antares-ztf-classification-context-tests.log
```

New regressions cover exact catalogue values and identities, per-row provenance,
parity with LSST paths, debt disjointness, 316 retained measurements, public
crossmatch retrieval/replay, a matching and nonmatching catalogue predicate, and
continued rejection of unsupported candidate classification. Both CI workflows
include the new module. No intermediate CI or live rerun is needed for these
five mappings; retain final checks on the eventual main-target SHA.
