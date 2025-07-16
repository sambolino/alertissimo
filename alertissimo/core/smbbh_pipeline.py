# alertissimo/core/smbbh_pipeline.py
import logging
from alertissimo.core.schema import WorkflowIR
from alertissimo.core.smbbh_ir import smbbh_ir
from alertissimo.core.brokers.alerce import ALeRCEBroker
from alertissimo.core.brokers.lasair import LasairBroker
from alertissimo.core.brokers.antares import AntaresBroker
from alertissimo.core.brokers.fink import FinkBroker

logger = logging.getLogger("smbbh-pipeline")
logging.basicConfig(level=logging.INFO)

def run_pipeline(ir: WorkflowIR):
    logger.info(f"Running pipeline: {ir.name}")

    oid = ir.confirm.object_id if ir.confirm and ir.confirm.object_id else "ZTF21abxyz01"

    # Available broker instances
    AVAILABLE_BROKERS = {
        "alerce": ALeRCEBroker,
        "lasair": LasairBroker,
        "antares": AntaresBroker,
        "fink": FinkBroker
    }

    BROKERS = {}
    for src in ir.confirm.sources:
        name = src.broker.lower()
        if name in AVAILABLE_BROKERS and name not in BROKERS:
            BROKERS[name] = AVAILABLE_BROKERS[name]()

    # Step 1: Confirmation
    agreement = 0
    total_sources = len(ir.confirm.sources) if ir.confirm else 0

    if not ir.confirm or not ir.confirm.sources:
        logger.warning("No confirmation sources defined in workflow IR.")
    else:
        logger.info(f"Confirming alert {oid} using {total_sources} brokers...")
        for src in ir.confirm.sources:
            broker_name = src.broker.lower()
            broker = BROKERS.get(broker_name)

            if not broker:
                logger.warning(f"Unsupported broker '{src.broker}' in confirmation sources.")
                continue

            data = broker.get_object_data(oid)
            if data:
                agreement += 1
                logger.info(f"Confirmed by {broker_name.capitalize()}.")
            else:
                logger.info(f"{broker_name.capitalize()} did not confirm alert.")

    if agreement < ir.confirm.required_agreement:
        logger.warning(f"Alert confirmation failed: {agreement}/{total_sources} brokers.")
        return

    logger.info(f"Alert confirmed by {agreement}/{total_sources} brokers.")

    # 2. ALeRCE retrieves ZTF curves
    ztf_lc = BROKERS["alerce"].get_lightcurve(oid)
    if ztf_lc:
        logger.info("Retrieved ZTF light curve from ALeRCE.")

    # 3. Lasair retrieves multiwavelength & historical context (stub for now)
    lasair_data = BROKERS["lasair"].get_object_data(oid)
    if lasair_data:
        logger.info("Stub: Lasair multiwavelength crossmatch complete.")

    logger.info("Pipeline logic continues here...")

if __name__ == "__main__":
    run_pipeline(smbbh_ir)

