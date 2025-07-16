# alertissimo/run_orchestrator.py

import logging
from dotenv import load_dotenv
from alertissimo.core.orchestrator import run_ir
from alertissimo.core.smbbh_ir import smbbh_ir

def main():
    load_dotenv()  # Load LASAIR_TOKEN or other secrets from .env
    logging.basicConfig(level=logging.INFO)
    
    run_ir(smbbh_ir)

if __name__ == "__main__":
    main()
