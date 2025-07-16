# alertissimo/core/orchestrator.py
import logging
from alertissimo.core.schema import WorkflowIR
from alertissimo.core.brokers import get_broker

logger = logging.getLogger("orchestrator")
logging.basicConfig(level=logging.INFO)


def run_ir(ir: WorkflowIR):
    logger.info(f"Running workflow: {ir.name}")

    # 1. Confirm alert
    if ir.confirm:
        oid = ir.confirm.object_id
        agreement = 0

        for src in ir.confirm.sources:
            broker = get_broker(src.broker)
            data = broker.get_object_data(oid)
            if data:
                agreement += 1

        if agreement < ir.confirm.required_agreement:
            logger.warning(f"Alert confirmation failed: {agreement}/{len(ir.confirm.sources)}")
            return
        logger.info(f"Alert confirmed by {agreement} brokers.")

    # 2. Retrieve light curves (optional enrich)
    for enrich_step in ir.enrich or []:
        broker = get_broker(enrich_step.source.broker)
        data = broker.get_lightcurve(oid)
        logger.info(f"Retrieved lightcurve from {enrich_step}: {bool(data)}")

    logger.info("Pipeline logic continues here...")

