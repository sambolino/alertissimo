#nothing here while we test dummy pipelines

'''
import argparse
from alertissimo.core.schema import WorkflowIR
from alertissimo.core.orchestrator import AlertWorkflow
import yaml

def load_ir_from_yaml(path):
    with open(path) as f:
        data = yaml.safe_load(f)
    return WorkflowIR(**data)

@cli.command()
def smbbh():
    """Run prototype SMBBH workflow"""
    from alertissimo.core.smbbh_pipeline import run_smbbh_pipeline
    run_smbbh_pipeline()

def main():
    parser = argparse.ArgumentParser(description="Run an Alertissimo workflow.")
    parser.add_argument("workflow", help="Path to workflow YAML file")
    parser.add_argument("--backend", choices=["ampel", "fink", "sql"], default="ampel")
    args = parser.parse_args()

    ir = load_ir_from_yaml(args.workflow)
    wf = AlertWorkflow(ir)

    if args.backend == "ampel":
        print(wf.to_ampel())
    elif args.backend == "fink":
        print(wf.to_fink())
    elif args.backend == "sql":
        print(wf.to_sql())

if __name__ == "__main__":
    main()
'''
