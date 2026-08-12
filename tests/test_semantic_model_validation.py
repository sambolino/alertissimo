from pathlib import Path
from itertools import count

import pytest
import yaml

from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import (
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.mapping_schema import InvalidSemanticPathError
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from alertissimo.data_layer.semantic_model import (
    SemanticModelValidationError,
    load_semantic_model_index,
    validate_portfolio_against_semantic_model,
)


def _portfolio(semantic_type: str) -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId("portfolio:test"),
        records=(
            SemanticRecord(
                internal_record_id=InternalRecordId("record:test"),
                semantic_type=semantic_type,
                fields={"identity.source_id": "ZTF1"},
            ),
        ),
    )


def _execution() -> ExecutionResult:
    provenance = InternalExecutionProvenance(
        internal_execution_id=InternalExecutionId("execution:test"),
        broker="lasair",
        origin="ztf",
        endpoint="object",
    )
    return ExecutionResult(
        payload={"objectId": "ZTF1"}, execution_provenance=provenance
    )


def _mapping(tmp_path, semantic_type: str):
    path = tmp_path / f"{semantic_type.split('@', 1)[0]}.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "broker": "lasair",
                "origin": "ztf",
                "payloads": {"object": {"endpoint": "object", "path": "."}},
                "mappings": {
                    f"{semantic_type}.identity.source_id": ["object#objectId"]
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def test_real_ontology_builds_lexical_index():
    index = load_semantic_model_index()

    assert {"detection", "summary", "classification", "crossmatch"} <= index.containers
    assert "source_id" in index.fields
    assert index.edge_types
    assert "--association--" in index.edge_types


def test_temporary_ontology_index_ignores_dynamic_declarations(tmp_path):
    path = tmp_path / "ontology.yaml"
    path.write_text(
        "# ignored\n<detection>:\n  <_internal>:\n  <{filter}>:\n"
        "  [source_id]:\n  [{field}]:\n--followup_of-->:\n",
        encoding="utf-8",
    )

    index = load_semantic_model_index(path)

    assert index.containers == frozenset({"detection", "_internal"})
    assert index.fields == frozenset({"source_id"})
    assert index.edge_types == frozenset({"--followup_of-->"})


def test_valid_portfolio_passes():
    validate_portfolio_against_semantic_model(_portfolio("detection@ztf:lasair"))


def test_unknown_record_type_fails():
    with pytest.raises(SemanticModelValidationError, match="banana"):
        validate_portfolio_against_semantic_model(_portfolio("banana@ztf:lasair"))


def test_record_builder_semantic_validation_is_opt_in(tmp_path):
    ids = count()
    semantic_type = "detection@ztf:lasair"
    arguments = {
        "mappings_path": _mapping(tmp_path, semantic_type),
        "internal_portfolio_id": InternalPortfolioId("portfolio:test"),
        "record_id_factory": lambda: InternalRecordId(f"record:{next(ids)}"),
        "validate_semantic_model": True,
    }

    portfolio = build_portfolio_from_execution(_execution(), **arguments)
    assert portfolio.records[0].semantic_type == semantic_type


def test_record_builder_rejects_ontology_invalid_mapping(tmp_path):
    with pytest.raises(InvalidSemanticPathError, match="banana"):
        build_portfolio_from_execution(
            _execution(), mappings_path=_mapping(tmp_path, "banana@ztf:lasair")
        )

def test_semantic_enrichment_paths_and_summary_canonical_declaration():
 from alertissimo.data_layer.semantic_model.semantic_paths import SemanticPathModel
 model=SemanticPathModel.from_ontology()
 for path in ('summary@lsst:antares.time.snapshot_mjd','summary@antares.photometry.i.mag.mean','summary@antares.photometry.i.mag.chi2','summary@antares.photometry.i.mag.half_amplitude','summary@antares.photometry.i.mag.maximum_deviation_from_median','summary@antares.photometry.i.mag.excess_kurtosis','summary@antares.photometry.i.flux.chi2','summary@antares.photometry.i.flux.excess_kurtosis','summary@antares.photometry.i.flux.coefficient_of_variation','detection@lsst:antares.photometry.i.flux'):
  assert model.is_valid(path),path
 for path in ('summary@antares.photometry.i.mag.amplitude','summary@antares.photometry.i.mag.percent_amplitude','summary@antares.photometry.i.mag.kurtosis','summary@antares.photometry.i.flux.kurtosis','summary@antares.photometry.i.flux.mean_variance'):
  assert not model.is_valid(path),path
 ontology=(Path(__file__).parents[1]/'alertissimo/data_layer/semantic_model/ontology.yaml').read_text()
 summary=ontology.split('<summary>:',1)[1].split('\n<reference_image>:',1)[0]
 assert '--canonical_for--> <summary>@{producer}:{channel}' in summary
