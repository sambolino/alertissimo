# Development workstreams

Alertissimo separates shared infrastructure from independently owned UI, language,
and orchestration workstreams. These boundaries should remain explicit as the new
architecture develops.

## Shared/stable

`alertissimo/data_layer/**` contains the semantic ontology and model, provider
registry and mappings, execution infrastructure, Portfolio and runtime
representations, and generic presentation projections.

Changes here should be deliberate because every workstream depends on this shared
layer. Generic presentation projections belong here; application and framework UI
do not.

## UI

`alertissimo/ui/**` owns:

- Streamlit and application presentation
- result previews
- SemanticRecord search, detail, and per-Portfolio group views
- Portfolio views
- selection and workspace presentation

UI code must not implement orchestration, broker access, provider mappings, or DSL
parsing. It consumes normalized Portfolio serialization and generic Portfolio
projections from the shared data layer.

## DSL/NLP

`alertissimo/dsl/**` and `alertissimo/nlp/**` own parsing, language definition, NLP
interpretation, and eventual compilation into the canonical middle-layer
representation.

## Orchestration

`alertissimo/orchestration/**` is the new v2 middle-layer area for:

- declarative IR
- capability planning
- execution plans
- workflow, run, and result structures
- workflow continuation

The package currently establishes ownership boundaries only; implementation will
be added by the orchestration workstream.

## Legacy

`alertissimo/core/**` contains the existing broker adapters, orchestrator, and
schema. They remain temporarily because the current orchestration path depends on
them. Do not develop new architecture there.
