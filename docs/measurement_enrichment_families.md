# Measurement records and enrichment families

## Scope

The generic semantic record `detection` is renamed to `measurement`. It keeps its
existing identity, time, position, quality, photometry, forced-photometry and
phenomenon-specific substructures. No photometric/spectral subclasses, new
product containers, data-product enum aliases, time-series remodel or level
changes are introduced.

Provider mappings, temporal evidence paths, normalization, presentation and
executable examples use `measurement@producer:channel`. Native broker endpoint
and payload names, detection counts, and the scientific `within` detection mode
remain unchanged. A positive detection witness still requires the existing
photometric and identity evidence; the new noun alone does not prove detection.

This is a semantic record/path rename. Existing DSL predicates and serialized
Portfolios using `detection@...` must be regenerated or migrated to
`measurement@...`; this change does not introduce a compatibility alias.

## Families and composition

`enrichment` is an abstract container. Its concrete members are classification,
crossmatch, lightcurve, color_magnitude, color_color, spectrum and data_product.
Container `$is` expresses transitive membership without field copying or a new
path segment. The existing `$ref`, underscore projection and level mechanisms
continue composing fields. Abstract containers cannot be instantiated.

The Portfolio references `summary`, `measurement`, `enrichment` and `survey`.
Referencing the family admits its concrete descendants. Concrete records keep
their existing names, schemas and producer/channel qualifiers.

The `_data_product_core` block, including its type, format and role enums, is
unchanged. A cutout remains a data product whose type is cutout. A structured
spectrum remains distinct from an artifact identified by type=spectrum.

## DSL

Requirement nouns come from the Portfolio's declared record types and family
descendants. Enum values and nested structures are not shorthand nouns.
Recognizing a noun does not establish a provider retrieval capability.

```text
objects ZTF21abfmbix from ztf via fink
with enrichment
```

An abstract-family requirement expands deterministically to all concrete broker
Get operations currently admitted by capability validation for the candidate
origins. The broker is inherited from the candidate clause or supplied with
`via`. No new executable IR operation is introduced. For the current Fink/ZTF
registry, this emits classification, crossmatch, data-product and lightcurve
retrievals. Other brokers expand according to their own admitted capabilities.

Only supported source/origin combinations are included. Unsupported or deferred
retrievals are not admitted by the family request. No local color-color or
color-magnitude computations are invented. A family with no available retrievals
fails explicitly. Once a retrieval is admitted, its normal required-call failure
behavior remains in force; a runtime failure is not silently ignored.

```text
objects from ztf, lsst via alerce
with enrichment via fink
```

Expansion preserves candidate origins and the broker override. It uses the
supplied capability graph, emits ordinary canonical Get steps, and deduplicates
identical explicit requests and continuation steps. Existing planning, binding,
execution, normalization and replay operate on those steps.

Producer/method restrictions or predicates on an abstract family are not
silently distributed over heterogeneous children. Name a concrete product for
such constraints. Abstract-family predicates are rejected in this revision.

## Validation

The focused family tests cover transitive membership, invalid parents/cycles,
abstract instantiation, concrete paths, ontology-driven noun admission,
broker/source expansion, supplied graph behavior, continuation, replay and
required member failures. Existing provider mapping, temporal selection, DSL and
normalization suites cover the record rename.
