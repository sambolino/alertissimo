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


def run_ir(ir: WorkflowIR) -> IRResult:
    logger.info(f"Running workflow: {ir.name}")

    oid = ir.confirm.object_id if ir.confirm else None
    broker_object_snapshots = {}
    lightcurves = {}
    crossmatch_results = {}
    kafka_results = {}

    # Step 1: Confirm alert
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
            return IRResult({}, {}, {}, {})
        logger.info(f"Alert confirmed by {agreement} brokers.")

    # Step 2: Enrichment
    for enrich_step in ir.enrich or []:
        broker = get_broker(enrich_step.source.broker)
        name = broker.name.lower()

        if isinstance(enrich_step, LightcurveStep):
            data = broker.get_lightcurve(oid)
            lightcurves[name] = data
            logger.info(f"Retrieved lightcurve from {name}: {bool(data)}")

        elif isinstance(enrich_step, CrossmatchStep):
            object_data = broker_object_snapshots.get(name)
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

    return IRResult(
        object_snapshots=broker_object_snapshots,
        lightcurves=lightcurves,
        crossmatch_results=crossmatch_results,
        kafka_results=kafka_results,
    )

