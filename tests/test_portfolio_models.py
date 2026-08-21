"""Tests for the internal portfolio representation."""

import pytest

import alertissimo.data_layer.representations.portfolio as models
from alertissimo.data_layer.representations import (
    InternalEdgeId,
    InternalExecutionId,
    InternalExecutionProvenance,
    InternalPortfolioId,
    InternalRecordId,
    InternalRecordSource,
    Portfolio,
    PortfolioModelError,
    SemanticEdge,
    SemanticRecord,
)


def record(identifier: str, semantic_type: str, **fields: object) -> SemanticRecord:
    return SemanticRecord(InternalRecordId(identifier), semantic_type, fields)


def test_portfolio_allows_repeated_semantic_records():
    summary = record("rec:summary", "summary@ztf:lasair", **{"identity.object_id": "ZTF25abc"})
    first = record("rec:detection:123", "detection@ztf:lasair", **{"time.mjd": 60321.123})
    second = record("rec:detection:124", "detection@ztf:lasair", **{"time.mjd": 60321.124})
    portfolio = Portfolio(InternalPortfolioId("portfolio:1"), (summary, first, second))

    detections = portfolio.records_of_type("detection@ztf:lasair")
    assert len(portfolio.records) == 3
    assert len(detections) == 2
    assert {item.internal_record_id for item in detections} == {
        InternalRecordId("rec:detection:123"),
        InternalRecordId("rec:detection:124"),
    }
    assert [item.get("time.mjd") for item in detections] == [60321.123, 60321.124]


def test_record_fields_are_relative_paths_and_allow_semantic_provenance():
    item = record(
        "rec:valid",
        "detection@ztf:lasair",
        **{
            "identity.object_id": "ZTF25abc",
            "time.mjd": 60321.123,
            "photometry.g.psf.mag": 19.46,
            "provenance.producer.name": "ZTF",
            "provenance.channel.name": "public",
        },
    )
    assert item.get("provenance.producer.name") == "ZTF"
    assert item.get("provenance.channel.name") == "public"


@pytest.mark.parametrize(
    "field_path",
    [
        "detection@ztf:lasair.photometry.g.psf.mag",
        "portfolio.detection@ztf:lasair.photometry.g.psf.mag",
        "portfolio.detection.photometry.g.psf.mag",
        "photometry.g@lsst.psf.mag",
    ],
)
def test_record_fields_reject_qualified_paths(field_path: str):
    with pytest.raises(PortfolioModelError, match="relative"):
        record(
            "rec:invalid",
            "detection@ztf:lasair",
            **{field_path: 19.46},
        )


def test_edge_fields_reject_qualified_paths():
    record_id = InternalRecordId("rec:target")

    with pytest.raises(PortfolioModelError, match="relative"):
        SemanticEdge(
            InternalEdgeId("edge:invalid"),
            "--association--",
            record_id,
            record_id,
            {"target@ztf.score": 0.9},
        )


def test_record_edges_are_first_class_and_require_existing_local_participants():
    detection = record("rec:detection", "detection@ztf:lasair", **{"time.mjd": 1.0})
    spectrum = record("rec:spectrum", "spectrum@gemini:archive", **{"identity.source_id": "s1"})
    edge = SemanticEdge(
        InternalEdgeId("edge:followup"),
        "--followup_of-->",
        spectrum.internal_record_id,
        detection.internal_record_id,
        {
            "basis": "candidate workflow",
            "score": 0.95,
            "provenance.producer.name": "Alertissimo",
        },
    )
    portfolio = Portfolio(InternalPortfolioId("portfolio:edge"), (detection, spectrum), (edge,))

    assert portfolio.edges == (edge,)
    assert edge.subject == spectrum.internal_record_id
    assert edge.target == detection.internal_record_id
    assert edge.get("basis") == "candidate workflow"
    assert edge.get("score") == 0.95
    assert edge.get("provenance.producer.name") == "Alertissimo"
    assert not detection.has("--followup_of-->")

    missing = SemanticEdge(
        InternalEdgeId("edge:missing"),
        "--association--",
        detection.internal_record_id,
        InternalRecordId("rec:missing"),
    )
    with pytest.raises(PortfolioModelError, match="target record"):
        Portfolio(InternalPortfolioId("portfolio:invalid"), (detection,), (missing,))


def test_portfolio_edges_are_local_adjacency_and_other_portfolio_need_not_be_loaded():
    local = InternalPortfolioId("portfolio:galaxy")
    remote = InternalPortfolioId("portfolio:star")
    edge = SemanticEdge(
        InternalEdgeId("edge:association:1"),
        "--association--",
        local,
        remote,
        {"basis": "catalog association"},
    )

    portfolio = Portfolio(local, edges=(edge,))

    assert portfolio.edges == (edge,)
    assert edge.subject == local
    assert edge.target == remote


def test_nondirectional_portfolio_edge_can_be_stored_from_each_local_perspective():
    galaxy = InternalPortfolioId("portfolio:galaxy")
    star = InternalPortfolioId("portfolio:star")
    edge_id = InternalEdgeId("edge:association:shared")

    galaxy_view = SemanticEdge(edge_id, "--association--", galaxy, star)
    star_view = SemanticEdge(edge_id, "--association--", star, galaxy)

    assert Portfolio(galaxy, edges=(galaxy_view,)).edges == (galaxy_view,)
    assert Portfolio(star, edges=(star_view,)).edges == (star_view,)
    assert galaxy_view.internal_edge_id == star_view.internal_edge_id


def test_directional_portfolio_edge_preserves_semantic_orientation_in_both_adjacency_lists():
    galaxy = InternalPortfolioId("portfolio:galaxy")
    transient = InternalPortfolioId("portfolio:transient")
    edge_id = InternalEdgeId("edge:host:shared")

    galaxy_view = SemanticEdge(edge_id, "--host_of-->", galaxy, transient)
    transient_view = SemanticEdge(edge_id, "--host_of-->", galaxy, transient)

    assert Portfolio(galaxy, edges=(galaxy_view,)).edges == (galaxy_view,)
    assert Portfolio(transient, edges=(transient_view,)).edges == (transient_view,)


def test_portfolio_edge_must_be_incident_on_the_portfolio_that_stores_it():
    edge = SemanticEdge(
        InternalEdgeId("edge:remote"),
        "--association--",
        InternalPortfolioId("portfolio:a"),
        InternalPortfolioId("portfolio:b"),
    )

    with pytest.raises(PortfolioModelError, match="not incident"):
        Portfolio(InternalPortfolioId("portfolio:c"), edges=(edge,))


def test_mixed_portfolio_and_record_edge_endpoints_are_rejected():
    with pytest.raises(PortfolioModelError, match="both be portfolio IDs or both be record IDs"):
        SemanticEdge(
            InternalEdgeId("edge:mixed"),
            "--association--",
            InternalPortfolioId("portfolio:a"),
            InternalRecordId("record:a"),
        )


def test_execution_provenance_is_call_scoped_and_source_is_compact():
    execution_id = InternalExecutionId("exec:lasair:ztf:object:1")
    execution = InternalExecutionProvenance(
        execution_id,
        broker="lasair",
        origin="ztf",
        endpoint="object",
        params={"objectId": "ZTF25abc"},
        status="success",
    )
    source = InternalRecordSource(execution_id, "candidates", "candidates[]", 4)
    item = SemanticRecord(
        InternalRecordId("rec:detection:source"),
        "detection@ztf:lasair",
        {"identity.object_id": "ZTF25abc"},
        source,
    )
    portfolio = Portfolio(
        InternalPortfolioId("portfolio:source"), (item,), executions=(execution,)
    )

    assert portfolio.execution(execution_id) is execution
    assert item.internal_source == source
    assert execution not in portfolio.records
    assert "internal_execution_id" not in item.fields


@pytest.mark.parametrize("kind", ["record", "edge", "execution"])
def test_duplicate_internal_ids_are_rejected(kind: str):
    first = record("rec:first", "summary@ztf:lasair")
    kwargs: dict[str, object] = {"records": (first,)}
    if kind == "record":
        kwargs["records"] = (first, record("rec:first", "detection@ztf:lasair"))
    elif kind == "edge":
        edge = SemanticEdge(InternalEdgeId("edge:1"), "--association--", first.internal_record_id, first.internal_record_id)
        kwargs["edges"] = (edge, edge)
    else:
        execution = InternalExecutionProvenance(InternalExecutionId("exec:1"), "lasair", "ztf", "object")
        kwargs["executions"] = (execution, execution)
    with pytest.raises(PortfolioModelError, match=f"duplicate internal {kind} ID"):
        Portfolio(InternalPortfolioId(f"portfolio:{kind}"), **kwargs)


def test_mappings_are_defensively_copied_and_top_level_immutable():
    record_fields = {"time.mjd": 1.0}
    edge_fields = {"basis": "initial"}
    params = {"objectId": "ZTF25abc"}
    item = SemanticRecord(InternalRecordId("rec:1"), "detection@ztf:lasair", record_fields)
    edge = SemanticEdge(InternalEdgeId("edge:1"), "--association--", item.internal_record_id, item.internal_record_id, edge_fields)
    execution = InternalExecutionProvenance(InternalExecutionId("exec:1"), "lasair", "ztf", "object", params)
    record_fields["time.mjd"] = 2.0
    edge_fields["basis"] = "changed"
    params["objectId"] = "changed"

    assert item.get("time.mjd") == 1.0
    assert edge.get("basis") == "initial"
    assert execution.params["objectId"] == "ZTF25abc"
    with pytest.raises(TypeError):
        item.fields["new"] = True


def test_convenience_helpers_are_deterministic():
    detection = record("rec:detection", "detection@ztf:lasair", **{"time.mjd": 1.0})
    spectrum = record("rec:spectrum", "spectrum@gemini:archive")
    edge = SemanticEdge(InternalEdgeId("edge:1"), "--followup_of-->", spectrum.internal_record_id, detection.internal_record_id, {"basis": "follow-up"})
    execution = InternalExecutionProvenance(InternalExecutionId("exec:1"), "lasair", "ztf", "object")
    portfolio = Portfolio(InternalPortfolioId("portfolio:helpers"), (detection, spectrum), (edge,), (execution,))

    assert detection.has("time.mjd") and detection.get("time.mjd") == 1.0
    assert not detection.has("missing") and detection.get("missing", "default") == "default"
    assert edge.has("basis") and edge.get("basis") == "follow-up"
    assert portfolio.get_record("rec:detection") is detection
    assert portfolio.get_edge(InternalEdgeId("edge:1")) is edge
    assert portfolio.semantic_types() == ("detection@ztf:lasair", "spectrum@gemini:archive")
    assert portfolio.edges_of_type("--followup_of-->") == (edge,)
    assert portfolio.execution("exec:1") is execution


def test_module_has_no_execution_parsing_or_field_trace_models():
    for name in (
        "InternalFieldProvenance",
        "FieldProvenance",
        "InternalValueProvenance",
        "InternalValueTrace",
        "Executor",
        "PayloadResolver",
        "RecordBuilder",
        "Kafka",
    ):
        assert not hasattr(models, name)
