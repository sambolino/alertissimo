# Alertissimo semantic model

`ontology.yaml` is the canonical Alertissimo semantic model / ontology.

It uses an ordered YAML-like ontology notation. It is not ordinary generic YAML
for direct semantic consumption.

Repeated directives, order, and scope may be meaningful. A plain
`yaml.safe_load` pass may be useful only as a low-level syntax step where safe,
but it is not sufficient to interpret the ontology.

A dedicated ontology loader/validator will be responsible for interpreting
this file.
