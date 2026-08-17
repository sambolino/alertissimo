# Alertissimo DSL verbs

The DSL remains future work. Its verbs should compile to the canonical semantic
operation classes rather than introduce a second operation model.

| Semantic category | Representative IR classes | Future DSL verbs |
| --- | --- | --- |
| `GetStep` | `GetLightcurveStep`, `GetCrossmatchStep`, `GetCutoutStep` | `get lightcurve`, `get crossmatch`, `get cutout` |
| `SearchStep` | `SemanticSearchStep`, `ConeSearchStep`, `SqlQueryStep` | `search`, `cone search`, `sql query` |
| `AnalyzeStep` | `ClassifyStep`, `AggregateStep`, `CompareStep` | `classify`, `aggregate`, `compare` |
| `ActionStep` | `FollowupRequestStep`, `NotifyStep`, `ExportStep` | `request followup`, `notify`, `export` |

Target syntax in a future DSL or UI must compile into a `TargetSelector`. For
example, an object target would produce
`TargetSelector(ids=["ZTF18abc"], kind="object")`; it does not define a fifth
Step category. No DSL parser is implemented by this document.
