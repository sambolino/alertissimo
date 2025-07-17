import logging
from dotenv import load_dotenv
from alertissimo.core.orchestrator import run_ir
from alertissimo.core.smbbh_ir import smbbh_ir

def main():
    load_dotenv()
    logging.basicConfig(level=logging.INFO)

    results = run_ir(smbbh_ir)
    print("Confirmed objects:")
    for broker, snapshot in results.object_snapshots.items():
        print(f"- {broker}: {type(snapshot)}")

    print("\nLight curves:")
    for broker, lc in results.lightcurves.items():
        print(f"- {broker}: {len(lc) if lc is not None else 0} records")

    print("\nCrossmatches:")
    for broker, cm in results.crossmatch_results.items():
        print(f"- {broker}: {len(cm) if cm else 0} matches")

    print("\nKafka monitoring:")
    for broker, monitored in results.kafka_results.items():
        print(f"- {broker}: {'✔' if monitored else '✘'}")

if __name__ == "__main__":
    main()
