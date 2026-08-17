# Target selection in the orchestration IR

Target selection is an explicit, composed IR value:

```python
TargetSelector(ids=["ZTF18abbuksn"], kind="object")
```

`TargetSelector.ids` is a nonempty, duplicate-free list of nonblank identifiers.
Its optional `kind` records the intended entity namespace (`object`, `alert`,
`source`, or `detection`) when that namespace is known. The selector is composed
onto operations that accept a target; target-bearing is not itself a semantic
Step family.

The semantic categories remain `GetStep`, `SearchStep`, `AnalyzeStep`, and
`ActionStep`. This keeps retrieval, discovery, analysis, and outward effects as
the public conceptual model while allowing unrelated operations to share the
same target value representation without inheritance.

For now, `kind` is metadata only. Namespace-aware provider planning and entity
resolution are deferred until identifier namespaces are formally modeled.
Workflow context and step-output references are also outside this model. A
future DSL and UI should compile their target syntax into `TargetSelector`; this
change does not implement either compiler.

`CompareStep` keeps its comparison operand separate from entity selection. Its
`target` selects the astronomical entities being analyzed through a
`TargetSelector`, while `comparison_target` names the semantic value, assertion,
or representation to compare (for example, `"classification"`). A comparison
operand may be declared without an entity selector when a future workflow context
will provide the entity set.
