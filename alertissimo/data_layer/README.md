# Alertissimo data layer

The data layer turns provider-native data into Alertissimo semantic representations. It owns provider endpoint declarations, mappings, physical endpoint execution, the semantic model/ontology, runtime interpreters, and internal representations such as `Portfolio`.

It does not own workflows, DSL, UI, scheduling, Kafka/live alert control, or orchestration policy.
