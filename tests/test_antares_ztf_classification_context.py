"""Catalogue classification evidence stays on matched ANTARES/ZTF records."""

from copy import deepcopy
from itertools import count
import json
from pathlib import Path

import pytest
import yaml

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.paths import PROVIDERS_ROOT
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.record_builder import build_portfolios_from_execution
from alertissimo.orchestration.ir import GetClassificationStep, Source
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.validation import validate_step_capabilities


FIXTURES = Path(__file__).parent / "fixtures/antares/ztf"
OID = "ZTF20aafqubg"
GAIA = "crossmatch@gaia:antares"
VARIABILITY = "crossmatch@gaia_variability:antares"
PROBABILITIES = {
    f"classification.assessment.gaia_dsc_{label}.probability": f"classprob_dsc_combmod_{label}"
    for label in ("galaxy", "quasar", "star")
}


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


def rich_locus():
    # Independently captured core and lazy relationships, assembled only in memory.
    payload = fixture("get_by_ztf_object_id")
    payload["alerts"] = fixture("alerts")
    payload["catalog_objects"] = fixture("catalog_objects")
    return payload


@pytest.fixture(scope="module")
def graph():
    return build_capability_graph()


class Executor:
    def __init__(self, *, rich=True):
        self.calls, self.ids = [], count()
        self.rich = rich

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert (broker, origin, endpoint) == ("antares", "ztf", "get_by_ztf_object_id")
        assert dict(params or {}) == {"ztf_object_id": OID}
        self.calls.append((endpoint, dict(params or {})))
        return ExecutionResult(payload=deepcopy(rich_locus() if self.rich else fixture("get_by_ztf_object_id")),
            execution_provenance=InternalExecutionProvenance(
                internal_execution_id=InternalExecutionId(f"antares-context:{next(self.ids)}"),
                broker=broker, origin=origin, endpoint=endpoint, params=dict(params or {}),
            ))


def test_frozen_catalogue_fields_keep_values_identity_and_source_rows():
    execution = Executor().execute("antares", "ztf", "get_by_ztf_object_id", {"ztf_object_id": OID})
    portfolio, = build_portfolios_from_execution(execution, validate_semantic_model=True)
    gaia, = (r for r in portfolio.records if r.semantic_type == GAIA)
    variability, = (r for r in portfolio.records if r.semantic_type == VARIABILITY)
    catalogues = fixture("catalog_objects")
    gaia_row, = catalogues["gaia_dr3_gaia_source"]
    variability_row, = catalogues["gaia_dr3_variability"]
    assert gaia.get("identity.object_id") == gaia_row["source_id"]
    assert variability.get("identity.object_id") == variability_row["source"]
    for field, raw in PROBABILITIES.items():
        assert gaia.get(field) == gaia_row[raw]
    assert variability.get("classification.assessment.gaia_variability.class") == variability_row["class"] == "RS"
    assert variability.get("classification.assessment.gaia_variability.method") == variability_row["classifier"] == "nTransits:5+"
    assert gaia.internal_source.payload_key == "locus_catalog_gaia"
    assert variability.internal_source.payload_key == "locus_catalog_gaia_variability"
    assert gaia.internal_source.payload_index == variability.internal_source.payload_index == 0
    assert gaia.internal_source != variability.internal_source
    assert not any(r.semantic_type.startswith("classification@") for r in portfolio.records)
    assert not any("classification" in field for r in portfolio.records
                   if r.semantic_type == "summary@ztf:antares" for field in r.fields)
    assert sum(r.semantic_type == "measurement@ztf:antares" for r in portfolio.records) == 316


def test_ztf_uses_existing_lsst_semantic_paths_and_removes_only_mapped_debt():
    ztf = yaml.safe_load((PROVIDERS_ROOT / "antares/ztf/mappings.yaml").read_text())["mappings"]
    lsst = yaml.safe_load((PROVIDERS_ROOT / "antares/lsst/mappings.yaml").read_text())["mappings"]
    paths = [GAIA + "." + path for path in PROBABILITIES]
    paths += [VARIABILITY + ".classification.assessment.gaia_variability." + leaf for leaf in ("class", "method")]
    for path in paths:
        assert ztf[path] == lsst[path]
    debt = yaml.safe_load((PROVIDERS_ROOT / "antares/ztf/unmapped_fields.yaml").read_text())["unmapped"]
    remaining = {name for item in debt for name in item}
    assert not {raw for path in paths for raw in ztf[path]} & remaining
    # Unverified anomaly outputs and filter-tag membership are not physical classes.
    assert "locus#properties.anomaly_score" in remaining
    assert "locus#properties.anomaly_mask" in remaining
    assert "locus#properties.anomaly_type" in remaining


def test_public_crossmatch_retrieval_and_continuation_use_catalogue_predicate(graph):
    executor = Executor()
    first = execute_dsl(f"object {OID} from ztf via antares\nwith crossmatch from gaia via antares\n",
                        graph=graph, executor=executor, continue_from=None)
    snapshot = first.to_dict()
    selected = execute_dsl(
        "filter crossmatch@gaia:antares.classification.assessment.gaia_dsc_star.probability >= 0.99\n",
        graph=graph, executor=executor, continue_from=first,
    )
    assert {summary_object_identity(p) for p in selected.portfolios} == {("ztf", OID)}
    assert sum(r.semantic_type == "measurement@ztf:antares" for p in selected.portfolios for r in p.records) == 316
    rejected = execute_dsl(
        "filter crossmatch@gaia:antares.classification.assessment.gaia_dsc_star.probability >= 1\n",
        graph=graph, executor=executor, continue_from=selected,
    )
    assert rejected.portfolios == ()
    assert first.to_dict() == snapshot
    assert selected.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert len(executor.calls) == 1


def test_missing_catalogue_relationship_supplies_no_invented_evidence(graph):
    result = execute_dsl(f"object {OID} from ztf via antares\nwith crossmatch from gaia via antares\n",
                         graph=graph, executor=Executor(rich=False), continue_from=None)
    assert {summary_object_identity(p) for p in result.portfolios} == {("ztf", OID)}
    assert not any(r.semantic_type.startswith(("classification@", "crossmatch@"))
                   for p in result.portfolios for r in p.records)


def test_candidate_get_does_not_promote_catalogue_classification_to_candidate_evidence(graph):
    step = GetClassificationStep(sources=[Source(broker="antares", origin="ztf")])
    assert validate_step_capabilities(step, graph).status == "supported"
    source = f"object {OID} from ztf via antares\nwith classification via antares\n"
    assert validate_dsl(source, graph=graph, continue_from=None).is_runnable
    executor = Executor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == [("get_by_ztf_object_id", {"ztf_object_id": OID})]
    assert not any(r.semantic_type.startswith("classification@")
                   and r.semantic_type != "classification@headline:antares"
                   for p in result.portfolios for r in p.records)
    headline, = [r for p in result.portfolios for r in p.records
                 if r.semantic_type == "classification@headline:antares"]
    assert headline.get("best.taxon") is None
