Alertissimo DSL verbs 1.0

| IR Class              | DSL Verb     | DSL Syntax Example                                                       |
| --------------------- | ------------ | ------------------------------------------------------------------------ |
| `FilterCondition`     | `filter`     | `filter attribute=magpsf op="<" value=19.5 source=fink`                  |
| `FindObject`          | `find`       | `find object_id=ZTF18abc sources=[fink, lasair]`                         |
| `ConfirmationRule`    | `confirm`    | `confirm object_id=ZTF18abc sources=[fink, lasair] required_agreement=2` |
| `Classifier`          | `classify`   | `classify method=rf model=ztf_supernova source=alerce`                   |
| `ScoringRule`         | `score`      | `score name=sn_score formula="prob_SN * 0.8 + prob_TDE * 0.2"`           |
| `ActStep`             | `act`        | `act export=results.csv path=/tmp/alerts/ notify=you@example.com`        |
| `LightcurveStep`      | `lightcurve` | `lightcurve source=fink`                                                 |
| `CrossmatchStep`      | `crossmatch` | `crossmatch catalogs=[SDSS, Gaia] source=alerce`                         |
| `CutoutStep`          | `cutout`     | `cutout source=antares`                                                  |
| `KafkaStep`           | `monitor`    | `monitor source=fink`                                                    |
| `WorkflowIR.schedule` | `schedule`   | `schedule cron="0 * * * *"`                                              |
| `WorkflowIR.name`     | `name`       | `name "SMBBH Search Workflow"`                                           |

