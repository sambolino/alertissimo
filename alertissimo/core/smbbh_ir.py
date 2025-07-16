from alertissimo.core.schema import (
    WorkflowIR,
    Source,
    ConfirmationRule,
    FilterCondition,
    EnrichmentStep,
    LightcurveStep,
    CrossmatchStep,
    Classifier,
    ScoringRule,
    ActStep,
)

smbbh_ir = WorkflowIR(
    name="smbbh-discovery-workflow",
    schedule=None,  # Optional: cron expression if periodic

    confirm=ConfirmationRule(
        object_id="ZTF25aazqavg",  # Replace with testable ZTF ID
        required_agreement=3,
        sources=[
            Source(broker="fink"),
            Source(broker="alerce"),
            Source(broker="lasair"),
            Source(broker="antares"),
        ]
    ),

    filter=[
        FilterCondition(attribute="rmag", op="<", value=19.5, source=Source(broker="alerce")),
        FilterCondition(attribute="ncandgp", op=">", value=2, source=Source(broker="alerce")),
    ],

    enrich=[
        LightcurveStep(
            type="historical_lightcurve",
            source=Source(broker="alerce"),
            params={"survey": "ztf"}
        ),
        CrossmatchStep(
            type="crossmatch",
            source=Source(broker="lasair"),
            #params={"catalogs": ["Pan-STARRS", "WISE", "XMM", "GALEX"]}
        ),
        CrossmatchStep(
            type="crossmatch",
            #type="xray_match",
            source=Source(broker="antares"),
            #params={"catalog": "eROSITA"}
        ),
        EnrichmentStep(
            type="realtime_monitoring",
            source=Source(broker="lasair"),
            params={"kafka": True}
        )
    ],

    classify=[
        Classifier(method="periodicity_detection", model="fourier_v1", source=Source(broker="custom"))
    ],

    score=[
        ScoringRule(
            name="smbbh_priority",
            formula="periodicity_score * 0.6 + multiwavelength_score * 0.4"
        )
    ],

    act=[
        ActStep(export="csv", path="smbbh_candidates.csv"),
        ActStep(notify="slack", path="smbbh_alerts")
    ]
)

