# Ontology metamodel

This document specifies the reusable notation and composition rules used by
[ontology.yaml](ontology.yaml). It is a documentation specification, not a
runtime import or a machine-readable schema.

A domain ontology supplies its own root, record vocabulary, level labels and
meanings, quantities, units, controlled values, and concrete edge declarations.
Alertissimo's Portfolio, astronomy record families, and L0–L8 meanings remain
in `ontology.yaml`; they are not mandatory vocabulary for another domain.

The extracted examples below use Alertissimo names to illustrate the notation.
Those names are examples, not metamodel requirements. References to a Portfolio
mean the structural root in these examples. The qualifier roles and placement
rules apply to records composed directly into their structural parent.

The notation is ordered and YAML-like. Repeated directives and their scope must
be preserved; ordinary YAML loading that overwrites duplicate keys is insufficient.
The current implementation provides a conservative lexical index and validation,
not a complete interpreter of all the rules documented here.

## Levels

A domain declares its level vocabulary. Levels are metadata, not path components.
Declaration order and scope determine inherited levels; fields may override them
or belong to multiple levels. A `$ref: <container>(Ln)` selects compatible fields
recursively and retains the ancestor containers needed to reach them.
A wrapper may supply the contextual role and effective level of a nested value
without changing that quantity's level globally. The astronomy-specific profile
and examples are retained in `ontology.yaml`.

## Extracted notation rules

The following sections preserve the existing recipe wording. Section numbers
are retained to make the extraction traceable.

### 1. Semantic containers

```text
<container>
    Instantiable, path-bearing semantic grouping. Its name is preserved
    when composed into another structure.

    Example:

        <detection>:
          $ref: <photometry>(L1)

    allows paths such as:

        detection.photometry.g.psf.flux

    The container name is part of the meaning. It should not be introduced
    merely to mirror a storage layout or a broker payload section.
```

### 2. Fields

```text
[field]
    Resolvable value-bearing semantic element. A field may be a leaf or may
    contain nested fields.

    Examples:

        [ra]
        [object_id]
        [flux]
        [probability]

    A field name should describe the value, not its accidental source name.
    Source names that cannot yet be normalized may be carried by dynamic
    fields or by mapping metadata.
```

### 3. Parameterized containers and dynamic fields

```text
<{parameter}>
    Runtime-resolved, path-bearing semantic container. Used when the
    substituted value forms a namespace with fields or subcontainers below
    it.

    Example:

        <photometry>:
          <{filter}>:
            <psf>:
              [flux]

    allows:

        photometry.g.psf.flux
        photometry.r.psf.flux

    Parameterized containers are appropriate for filters, named
    classification outputs, color pairs, or other runtime values that behave
    as semantic namespaces.

[{field}]
    Dynamic resolvable extension field or terminal runtime field. Used for
    producer-, broker-, catalog-, or method-specific values not yet
    represented in the stable vocabulary. It may also represent a parameter
    that terminates the path rather than carrying descendants.

    Dynamic fields are escape hatches. They should not replace a stable
    reusable concept once that concept is clear.
```

### 4. Internal projections and reusable traits

```text
<_name>
    Non-instantiable field projection or reusable trait. An underscored
    element never appears as a semantic path component.

    A projection can import the contents of a semantic container without
    importing the container name itself:

        <forced_photometry>:
          $ref: <_photometry>

    allows:

        forced_photometry.g.psf.flux

    not:

        forced_photometry.photometry.g.psf.flux

    A trait can also be declared explicitly:

        <_classification_core>:
          [class]
          [probability]

        <classification>:
          <best>:
            $ref: <_classification_core>

    allows:

        classification.best.class
        classification.best.probability

    The underscored trait name is never propagated into the path.
```

### 4b. Edge carriers

```text
--edge--
    Abstract or concrete connection carrier between semantic records. Edges
    are not dot-path containers and do not appear as children of the noun
    data tree. They belong to the connection plane.

    Examples:

        detection@vidojevica --followup_of--> detection@lsst:fink
        detection@lsst:fink --association-- detection@lvk:gcn

    The arrow, or lack of arrow, is part of the edge name. Direction is
    therefore explicit in the carrier symbol itself:

        --followup_of-->     directional
        --association--      nondirectional

    Edge carriers may have their own fields such as score, basis,
    time_delta, request_id, or provenance. These fields describe the
    connection assertion itself, not the subject record and not the target
    record.

$is: --edge--
    Declares that a concrete edge carrier is a kind of the abstract edge
    carrier. This is edge-plane inheritance, not noun-plane composition.
    It does not create dot-path segments and does not propagate fields into
    the subject or target records.

$edges:
    Declares the allowed edge participation of the enclosing record. If the
    declared edge is abstract, any concrete edge whose $is chain resolves to
    that abstract edge is allowed.
```

### 5. Single references

```text
$ref: <container>
    Allows one instance of an instantiable semantic container to appear in
    the current structure. The referenced container name remains in the
    path.

$ref: <container>(Ln)
    Allows fields of the referenced container that are valid at the selected
    level. Level selection is recursive and field-based. Ancestor containers
    needed to reach selected fields are retained as path scaffolding; sibling
    fields whose levels do not match are not selected.

    Example:

        <summary>:
          $ref: <photometry>(L0)

    may allow both:

        summary.photometry.g.magnitude_rate
        summary.photometry.g.psf.mean

    while not implying L1 detection measurements such as:

        summary.photometry.g.psf.fit_chi2

$ref: <_container>
    Imports only the referenced contents. The underscored source is not
    instantiable and does not add a path component.

Important:
    A reference is permissive, not mandatory. It declares that the enclosing
    structure may carry semantically compatible fields from the referenced
    concept. It does not require every record instance to contain all fields
    made available by the reference, and it does not require a normalizer to
    materialize absent fields. Presence, absence, reduction, and storage are
    runtime matters.
```

### 6. Repeated references

```text
$refs: <container>
    Declares that the current structure may collect zero or more instances
    of the referenced semantic entity.

    Example:

        <portfolio>:
          $refs: <summary>
          $refs: <detection>
          $refs: <crossmatch>

    $refs defines semantic cardinality. It does not pluralize the semantic
    noun and does not expose runtime array indexes in semantic paths.

    Repeated instances may have the same semantic path:

        portfolio.detection@lsst:fink
        portfolio.detection@lsst:fink
        portfolio.detection@lsst:fink

    The path identifies the kind of record and its semantic qualification,
    not necessarily one concrete instance. Implementations may use internal
    record identifiers, array positions, database keys, or object anchors to
    connect concrete instances. Such identifiers are storage details and are
    not part of the public semantic path grammar.
```

### 7. Intrinsically multi-valued fields

```text
type: array
    Used when a single field value is intrinsically a list or array. This is
    distinct from repeated semantic entities declared with $refs.

    Examples:

        cutouts.science
        lightcurve.points
```

### 11. Structural context carries meaning

```text
Do not repeat information already expressed by the enclosing hierarchy.

    detection.forced_photometry.g.psf.flux

means forced photometry on the science/detection side, while:

    detection.reference.forced_photometry.g.psf.flux

means forced photometry on the reference/template image.

Fields such as science_flux and template_flux are therefore unnecessary in
the semantic vocabulary. The reusable container supplies the measurement
concept; the parent structure supplies the role.
```

### 13. Qualifier grammar

```text
First-level semantic records may be qualified as:

    <record>@<producer>:<channel>

@producer
    Identifies who created the addressed record or datum. A producer may be
    a survey, catalog, broker science module, classifier, instrument,
    workflow, or internal Alertissimo module.

:channel
    Identifies the broker, archive, API, service, cache, or other route
    through which the record was received. It is delivery/audit information,
    not a claim of scientific authorship.

Examples:

    portfolio.summary@lsst.identity.object_id
    portfolio.detection@lsst:lasair.photometry.g.psf.flux
    portfolio.lightcurve@ztf:fink.points.photometry.r.psf.mag
    portfolio.crossmatch@gaia:fink.identity.object_id
    portfolio.classification@fink.best.class

The producer is the producer of the addressed value, not necessarily the
producer of the original alert packet. A single broker payload may therefore
split into several semantic records:

    detection@lsst:fink          LSST detection delivered through Fink
    classification@fink          Fink classification product
    crossmatch@gaia:fink         Gaia catalog match exposed by Fink

If Fink classification is delivered through another system, for example
AMPEL, the path may be:

    classification@fink:ampel

If AMPEL computes its own classification, the producer changes:

    classification@ampel
```

### 14. Qualifier scope

```text
In ordinary composition, @producer and :channel appear on first-level records
composed directly into their structural parent, normally <portfolio>. The
qualifier is inherited by nested fields of that record.

Valid:

    portfolio.detection@lsst:lasair.position.ra
    portfolio.lightcurve@alertissimo.points.photometry.r.psf.mag
    portfolio.crossmatch@gaia:fink.astrometric_solution.parallax

Invalid as ordinary field qualification:

    portfolio.detection.photometry.g@lsst.psf.flux
    portfolio.lightcurve.points.photometry.r@ztf.psf.mag

Edge participants are the exception. A connection may point to another
semantic record by using the record type with its qualifier:

    portfolio.detection@vidojevica --followup_of--> portfolio.detection@lsst:fink
    portfolio.detection@lsst:fink --association-- portfolio.detection@lvk:gcn

This is a reference to an existing record in the same portfolio, not a nested
copy of that record and not a second first-level record. Edge expressions are
connection-plane expressions, not ordinary dot-path field qualification.
```

### 15. Optional channel

```text
:channel is optional. If omitted, the delivery route is direct, unspecified,
irrelevant to the semantic operation, or identical to the producer and not
required for audit.

More detailed method, version, schema, timing, or payload information belongs
in <provenance>, not in the main semantic path.
```

### 16. Provenance as immediate context

```text
<provenance> describes the immediately enclosing record or assertion. This
rule is important because provenance can appear at several depths:

    detection.provenance
        provenance of the detection record

    edge.provenance
        provenance of a connection assertion

    target_record.provenance
        provenance of a related record after resolving an edge target

The canonical provenance roles are producer and channel. These mirror the
@producer:channel qualifier but may carry additional typed metadata:

    provenance.producer.type
    provenance.producer.name
    provenance.producer.version
    provenance.producer.detector_status.status
    provenance.channel.type
    provenance.channel.name

Detector status belongs to the producer side when it describes the reporting
instrument or detector at the time of the enclosing record. It should not be
confused with the channel that delivered the record.

Synonyms such as broker, publisher, origin, survey, mediator, and delivery
may be useful in DSL/NLP parsing, but the semantic model should normalize
them to producer or channel rather than adding parallel canonical branches.
```

### 17. Edges as connection carriers

```text
Dot paths describe contained data. Edges describe connections between
semantic records. The edge plane is separate from the noun/data plane:

    portfolio.detection@lsst:fink.photometry.g.psf.flux
        contained data field

    portfolio.detection@vidojevica --followup_of--> portfolio.detection@lsst:fink
        directed connection between records

    portfolio.detection@lsst:fink --association-- portfolio.detection@lvk:gcn
        nondirectional connection between records

Edge carrier symbols are meaningful. A symbol with an arrow is directional;
a symbol without an arrow is nondirectional. No additional direction field is
needed in the edge definition.

The abstract edge carrier is:

    --edge--

Concrete edge carriers declare:

    $is: --edge--

This means that the concrete edge inherits the abstract edge's edge-scoped
fields, constraints, and metadata. It is not equivalent to $ref in the noun
model. Inherited edge fields belong to the edge instance itself and must not
be exposed as dot-path children of either participating record.

A record declares possible edge participation with $edges:

    <detection>:
      $edges:
        --edge-- <detection>@{producer}:{channel}

If the named edge carrier is abstract, any concrete edge whose $is chain
resolves to that carrier is allowed. Thus a detection can participate in
--association--, --confirmation--, --followup_of-->, --revision_of-->, or
another registered edge type derived from --edge--, while the target
constraint still says that the other participant is a detection record.

Edge instances may carry scores, basis text, timing windows, provenance, and
edge-type-specific fields. Spatial, temporal, photometric, localization, or
radio quantities used as evidence should remain in their proper semantic
containers when they are measured data. The edge records the connection
assertion and its supporting metadata; it does not absorb all evidence into a
generic relation object.

Revisions are modeled as edge-plane connections for now. Use --revision_of-->
to link an update, correction, or retraction to the record it supersedes,
rather than introducing a separate revision container in the noun/data plane.
```

### 18. Concrete paths

```text
Concrete paths are formed from:

    - structural hierarchy
    - first-level producer/channel qualification
    - instantiable semantic containers
    - parameter substitution
    - resolvable fields

Examples:

    portfolio.summary@lsst.identity.object_id
    portfolio.summary@lsst.photometry.g.psf.mean
    portfolio.detection@lsst:lasair.position.ra
    portfolio.detection@lvk:gcn.localization.skymap
    portfolio.detection@fermi_gbm:gcn.gamma_ray.duration_t90
    portfolio.detection@swift_xrt:gcn.xray.flux
    portfolio.detection@lsst:lasair.photometry.g.aperture.flux
    portfolio.detection@lsst:lasair.reference.nearest_source.separation.total
    portfolio.detection@lsst:lasair.reference.forced_photometry.g.psf.flux
    portfolio.lightcurve@ztf:fink.points.photometry.r.psf.mag
    portfolio.spectrum@gemini:archive.feature.si_ii_6355.velocity
    portfolio.data_product@gemini:archive.uri
    portfolio.crossmatch@gaia:fink.identity.object_id
    portfolio.classification@fink.assessment.snia_vs_nonia.probability
    portfolio.survey@lsst:alertissimo.raw_alerts
    portfolio.survey@lsst:alertissimo.threshold.quality.signal_to_noise
    portfolio.survey@lsst:alertissimo.aggregate.separation.median

Connection-plane example:

    portfolio.detection@vidojevica --followup_of--> portfolio.detection@lsst:fink
```

### 19. Parser requirements

```text
A parser or Codex-generated implementation should:

    - preserve declaration order
    - preserve repeated level, $ref, and $refs directives
    - treat levels as scoped metadata, not YAML keys to be overwritten
    - apply level selection recursively down to fields
    - keep singular semantic nouns in public paths
    - avoid runtime array indexes in semantic paths
    - treat dynamic fields as last-resort extension points
    - track dynamic [{field}] usage and promote repeated concepts into the
      stable vocabulary through a controlled process
    - normalize source aliases to canonical enum values where a controlled
      vocabulary exists, while warning on unknown extension values
    - reject or warn against accidental interpretation by ordinary YAML
      loaders that would overwrite repeated keys
    - expose an effective-level view for each resolved field
    - provide an explain-path command showing how a semantic path was formed
    - resolve edge participants through implementation data structures, not
      through visible semantic-path contortions
```

### 20. Scope

```text
This specification does not define:

    - broker-specific field mappings
    - query syntax or transformation logic
    - execution semantics
    - runtime storage representation
    - selector, reducer, or freshness operators
    - internal record identifiers

The domain ontology defines its vocabulary. This metamodel defines composition rules, level
metadata, cardinality, provenance qualification, and edge grammar.
```
