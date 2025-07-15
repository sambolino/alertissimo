import requests
import logging
from alertissimo.config import LASAIR_TOKEN
from alertissimo.core.smbbh_ir import smbbh_ir
from alertissimo.core.schema import WorkflowIR, Source

logger = logging.getLogger("smbbh-pipeline")
logging.basicConfig(level=logging.INFO)


# --- API Functions ---

def alerce_object_data(oid: str):
    url = f"https://api.alerce.online/ztf/v1/objects/?oid={oid}"
    logger.info(f"Fetching ALeRCE object data: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logger.warning(f"ALeRCE failed: {response.status_code}")
        return {}

def lasair_object_data(oid: str):
    url = f"https://lasair-ztf.lsst.ac.uk/api/object/?objectId={oid}&token={LASAIR_TOKEN}&format=json"
    logger.info(f"Fetching Lasair object data: {url}")
    response = requests.get(url)
    if response.status_code == 200:
        return response.json()
    else:
        logger.warning(f"Lasair failed: {response.status_code}")
        return {}

def antares_object_data(oid: str):
    try:
        import antares_client
        result = antares_client.search.get_by_ztf_object_id(oid)
        logger.info(f"Retrieved ANTARES data for {oid}")
        return result
    except ImportError:
        logger.warning("antares-client not installed.")
        return {}

# Stub for Fink (pending permission)
def fink_object_data(oid: str):
    logger.info(f"Fink data for {oid} — stub")
    return {"fink_stub": True}


# --- Main Pipeline Execution ---

def run_pipeline(ir: WorkflowIR):
    logger.info(f"Running pipeline: {ir.name}")
    oid = ir.confirm.object_id if ir.confirm else "ZTF21abxyz01"

    # Step 1: Confirmation (mocked with live calls)
    agreement = 0
    for src in ir.confirm.sources:
        if src.broker == "alerce":
            data = alerce_object_data(oid)
        elif src.broker == "lasair":
            data = lasair_object_data(oid)
        elif src.broker == "antares":
            data = antares_object_data(oid)
        elif src.broker == "fink":
            data = fink_object_data(oid)
        else:
            continue

        if data:
            agreement += 1

    if agreement < ir.confirm.required_agreement:
        logger.warning(f"Alert confirmation failed: {agreement}/{len(ir.confirm.sources)} brokers.")
        return
    logger.info(f"Alert confirmed by {agreement} brokers.")

    # Continue with stubbed enrichment, classification, scoring
    logger.info("Pipeline logic continues here...")

# --- Entry point ---

if __name__ == "__main__":
    run_pipeline(smbbh_ir)

