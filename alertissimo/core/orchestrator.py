import logging
from dataclasses import dataclass
from typing import Any

from alertissimo.core.schema import *
from alertissimo.core.brokers import get_broker

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO)


@dataclass
class IRResult:
    object_snapshots: dict[str, Any]
    lightcurves: dict[str, Any]
    crossmatch_results: dict[str, Any]
    kafka_results: dict[str, bool]
    find_results: dict[str, Any]
    filter_results: dict[str, Any]
    classify_results: dict[str, Any]
    score_results: dict[str, Any]
    act_results: dict[str, Any]


def run_ir(ir: WorkflowIR) -> IRResult:
    logger.info(f"Running workflow: {ir.name}")

    # Prepare containers for results
    broker_object_snapshots = {}
    lightcurves = {}
    crossmatch_results = {}
    kafka_results = {}
    find_results = {}
    filter_results = {}
    classify_results = {}
    score_results = {}
    act_results = {}

    oid = ir.confirm.object_id if ir.confirm else None

    # === 1. Confirm alert ===
    if ir.confirm:
        agreement = 0
        for src in ir.confirm.sources:
            broker = get_broker(src.broker)
            name = broker.name.lower()
            data = broker.object_query(oid)
            if data:
                agreement += 1
                broker_object_snapshots[name] = data
        if agreement < ir.confirm.required_agreement:
            logger.warning(f"Alert confirmation failed: {agreement}/{len(ir.confirm.sources)}")
            return IRResult({}, {}, {}, {}, {}, {}, {}, {}, {})
        logger.info(f"Alert confirmed by {agreement} brokers.")

    # === 2. Find Object ===
    if ir.findobject:
        find_results = {}

        for src in ir.findobject.sources:
            broker = get_broker(src.broker)
            name = broker.name.lower()

            # Prepare query arguments, excluding 'sources'
            query_args = ir.findobject.dict(exclude={"sources", "required"})

            object_id = query_args.pop("object_id", None)
            if not object_id:
                raise ValueError("FindObject step missing object_id")

            # Perform the query
            result = broker.object_query(object_id, **query_args)
            #result = broker.object_query(**query_args)

            find_results[name] = result
            logger.info(f"Find object from {name}: {bool(result)}")

    # === 3. Filter ===
    for rule in ir.filter or []:
        broker = get_broker(rule.source.broker)
        name = broker.name.lower()
        result = broker.apply_filter(**rule.dict(exclude={"source"}))
        filter_results.setdefault(name, []).append(result)
        logger.info(f"Filter applied by {name}")

    # === 4. Classify ===
    for rule in ir.classify or []:
        broker = get_broker(rule.source.broker)
        name = broker.name.lower()
        result = broker.classify(**rule.dict(exclude={"source"}))
        classify_results.setdefault(name, []).append(result)
        logger.info(f"Classification by {name}")

    # === 5. Enrich ===
    for enrich_step in ir.enrich or []:
        broker = get_broker(enrich_step.source.broker)
        name = broker.name.lower()

        if isinstance(enrich_step, LightcurveStep):
            data = broker.get_lightcurve(oid)
            lightcurves[name] = data
            logger.info(f"Retrieved lightcurve from {name}: {bool(data)}")

        elif isinstance(enrich_step, CrossmatchStep):
            data = broker.crossmatch(oid)
            crossmatch_results[name] = data
            logger.info(f"Retrieved crossmatch from {name}: {bool(data)}")

        elif enrich_step.type == "realtime_monitoring":
            if hasattr(broker, "is_kafka_monitored"):
                result = broker.is_kafka_monitored(oid)
                kafka_results[name] = result
                logger.info(f"{name} Kafka monitoring result: {result}")
            else:
                logger.warning(f"{name} does not support Kafka monitoring.")

    # === 6. Scoring ===
    for rule in ir.score or []:
        broker = get_broker(rule.source.broker)
        name = broker.name.lower()
        result = broker.score(**rule.dict(exclude={"source"}))
        score_results.setdefault(name, []).append(result)
        logger.info(f"Scoring from {name}")

    # === 7. Actions ===
    for step in ir.act or []:
        broker = get_broker(step.source.broker)
        name = broker.name.lower()
        result = broker.perform_action(**step.dict(exclude={"source"}))
        act_results.setdefault(name, []).append(result)
        logger.info(f"Act step executed by {name}")

    return IRResult(
        object_snapshots=broker_object_snapshots,
        lightcurves=lightcurves,
        crossmatch_results=crossmatch_results,
        kafka_results=kafka_results,
        find_results=find_results,
        filter_results=filter_results,
        classify_results=classify_results,
        score_results=score_results,
        act_results=act_results,
    )
