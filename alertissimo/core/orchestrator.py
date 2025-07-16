# alertissimo/core/orchestrator.py
import logging
from alertissimo.core.schema import *
from alertissimo.core.brokers import get_broker

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO)


def run_ir(ir: WorkflowIR):
    logger.info(f"Running workflow: {ir.name}")

    # 1. Confirm alert
    if ir.confirm:
        oid = ir.confirm.object_id
        broker_object_snapshots = {}
        agreement = 0

        for src in ir.confirm.sources:
            broker = get_broker(src.broker)
            data = broker.get_object_data(oid)
            if data:
                agreement += 1
                broker_object_snapshots[src.broker] = data

        if agreement < ir.confirm.required_agreement:
            logger.warning(f"Alert confirmation failed: {agreement}/{len(ir.confirm.sources)}")
            return
        logger.info(f"Alert confirmed by {agreement} brokers.")
        #logger.info(broker_object_snapshots)

    # 2. Retrieve light curves (optional enrich)
    for enrich_step in ir.enrich or []:
        broker = get_broker(enrich_step.source.broker)
        
        if type(enrich_step) is LightcurveStep:
            data = broker.get_lightcurve(oid)
            logger.info(f"Retrieved lightcurve from {enrich_step}: {bool(data)}")
        
        elif type(enrich_step)is CrossmatchStep:
            data = broker.get_crossmatch(oid, broker_object_snapshots[broker.name.lower()])
            logger.info(f"Retrieved crossmatch record from {enrich_step}: {bool(data)}")
        
#        elif enrich_step.type == "xray_match":
#            if hasattr(broker, "extract_xray_matches"):
#                result = broker.extract_xray_matches(broker_object_snapshots[broker.name.lower()])
#                logger.info(f"Retrieved X-ray crossmatch from {broker.name}: {bool(result)}")
#            else:
#                logger.warning(f"{broker.name} does not support X-ray crossmatch.")

        elif enrich_step.type == "realtime_monitoring":
            logger.info(f"Checking Kafka AGN stream monitoring for {broker.name}")
            if hasattr(broker, "is_kafka_monitored"):
                result = broker.is_kafka_monitored(oid)
                logger.info(f"{broker.name} Kafka monitoring result: {result}")
            else:
                logger.warning(f"{broker.name} does not support Kafka monitoring.")


    logger.info("Pipeline logic continues here...")

