# Alertissimo data layer

The data layer turns provider-native data into Alertissimo semantic
representations. “Providers” is intentionally broader than “brokers”.

It owns:

- provider endpoint declarations
- provider mappings
- endpoint execution
- the semantic model / ontology
- runtime interpreters
- internal representations such as `Portfolio`

It does not own:

- workflows
- DSL
- planner
- UI
- scheduling
- Kafka/live alert control
- follow-up action policy
