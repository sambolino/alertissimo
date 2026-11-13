from alertissimo.data_layer.execution.registry import EndpointRegistry
from alertissimo.data_layer.representations import (
    InternalPortfolioId,
    InternalRecordId,
    Portfolio,
    SemanticRecord,
)
from alertissimo.data_layer.runtime.capability_graph import (
    CapabilityGraph,
    EndpointCapability,
    RequestConstraintCapability,
    build_capability_graph,
)
from alertissimo.dsl import lower_surface, parse_surface_script
from alertissimo.orchestration.binding import bind_endpoint
from alertissimo.orchestration.ir import (
    BooleanPredicate,
    ComparisonPredicate,
    PredicateLiteral,
    SemanticReference,
    SemanticSearchStep,
)
from alertissimo.orchestration.normalization import (
    evaluate_portfolio_predicate,
    prune_portfolios,
)
from alertissimo.orchestration.planner import plan_step, realize_predicate


def _endpoint(
    *,
    broker: str = "testbroker",
    origin: str = "testsurvey",
    endpoint: str = "search",
) -> EndpointCapability:
    return EndpointCapability(
        broker=broker,
        origin=origin,
        endpoint=endpoint,
        path=f"/{endpoint}",
        method="GET",
        operation_types=("object_search",),
        params=("kind", "score"),
        server_filters=("kind", "score"),
        projection_param=None,
        supports_projection=False,
        output_type="array",
    )


def _comparison(field: str, operator: str, value):
    return ComparisonPredicate(
        operator=operator,
        left=SemanticReference(semantic_type="summary", field_path=field),
        right=PredicateLiteral(value=value),
    )


def _portfolio(portfolio_id: str, records: list[tuple[str, str, dict]]) -> Portfolio:
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(portfolio_id),
        records=tuple(
            SemanticRecord(
                internal_record_id=InternalRecordId(record_id),
                semantic_type=semantic_type,
                fields=fields,
            )
            for record_id, semantic_type, fields in records
        ),
    )


def test_real_alerce_lsst_search_predicate_is_fully_pushable():
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "SN" AND '
        "best.probability >= 0.8\n"
    )
    compilation = lower_surface(surface)
    search = compilation.workflow.steps[0]
    assert isinstance(search, SemanticSearchStep)

    graph = build_capability_graph()
    plans = plan_step(search, graph)

    assert len(plans) == 1
    plan = plans[0]
    assert (plan.broker, plan.origin, plan.endpoint) == (
        "alerce",
        "lsst",
        "query_objects",
    )
    realization = plan.predicate_realization
    assert realization is not None
    assert realization.pushdown == search.predicate
    assert realization.residual is None
    assert realization.params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
        "probability": 0.8,
    }

    bound = bind_endpoint(search, plan, EndpointRegistry())
    assert bound.params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
        "probability": 0.8,
    }
    assert bound.endpoint_spec.fixed_params["survey"] == "lsst"


def test_general_qualified_where_reaches_same_alerce_physical_constraints():
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'where classification@lc_classifier.best.class = "SN" and '
        "classification@lc_classifier.best.probability >= 0.8\n"
    )
    compilation = lower_surface(surface)
    search = compilation.workflow.steps[0]

    plan = plan_step(search, build_capability_graph())[0]
    assert plan.predicate_realization.params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
        "probability": 0.8,
    }
    # The classification data requirement is still a separate semantic Step.
    assert len(compilation.workflow.steps) == 2


def test_partial_conjunction_pushdown_keeps_unsupported_part_residual():
    endpoint = _endpoint()
    graph = CapabilityGraph(
        endpoint_capabilities=(endpoint,),
        payload_capabilities=(),
        field_mapping_capabilities=(),
        transform_capabilities=(),
        semantic_record_capabilities=(),
        request_constraint_capabilities=(
            RequestConstraintCapability(
                broker=endpoint.broker,
                origin=endpoint.origin,
                endpoint=endpoint.endpoint,
                parameter="kind",
                semantic_path="summary.kind",
                operator="=",
            ),
        ),
    )
    pushable = _comparison("kind", "=", "SN")
    residual = _comparison("score", ">=", 0.8)
    predicate = BooleanPredicate(
        operator="and",
        operands=(pushable, residual),
    )

    realization = realize_predicate(predicate, endpoint=endpoint, graph=graph)

    assert realization.pushdown == pushable
    # A server-selected object can still contain several summary assertions.
    # Recheck kind and score together on one returned record.
    assert realization.residual == predicate
    assert realization.params == {"kind": "SN"}


def test_or_is_not_partially_pushed_down():
    endpoint = _endpoint()
    graph = CapabilityGraph(
        endpoint_capabilities=(endpoint,),
        payload_capabilities=(),
        field_mapping_capabilities=(),
        transform_capabilities=(),
        semantic_record_capabilities=(),
        request_constraint_capabilities=(
            RequestConstraintCapability(
                broker=endpoint.broker,
                origin=endpoint.origin,
                endpoint=endpoint.endpoint,
                parameter="kind",
                semantic_path="summary.kind",
                operator="=",
            ),
        ),
    )
    predicate = BooleanPredicate(
        operator="or",
        operands=(
            _comparison("kind", "=", "SN"),
            _comparison("score", ">=", 0.8),
        ),
    )

    realization = realize_predicate(predicate, endpoint=endpoint, graph=graph)

    assert realization.pushdown is None
    assert realization.residual == predicate
    assert realization.params == {}


def test_endpoint_without_request_semantics_leaves_whole_predicate_residual():
    endpoint = _endpoint()
    graph = CapabilityGraph((endpoint,), (), (), (), ())
    predicate = _comparison("kind", "=", "SN")

    realization = realize_predicate(predicate, endpoint=endpoint, graph=graph)

    assert realization.pushdown is None
    assert realization.residual == predicate
    assert realization.params == {}


def test_alerce_unsupported_probability_direction_remains_residual():
    surface = parse_surface_script(
        "objects from lsst via alerce\n"
        'with classification from lc_classifier where best.class = "SN" AND '
        "best.probability < 0.8\n"
    )
    search = lower_surface(surface).workflow.steps[0]
    plan = plan_step(search, build_capability_graph())[0]
    realization = plan.predicate_realization

    assert realization is not None
    assert realization.pushdown is not None
    assert realization.residual is not None
    assert realization.params == {
        "classifier": "lc_classifier",
        "class_name": "SN",
    }


def test_residual_classification_conjunction_must_match_one_record():
    predicate = BooleanPredicate(
        operator="and",
        operands=(
            ComparisonPredicate(
                operator="=",
                left=SemanticReference(
                    semantic_type="classification",
                    field_path="best.class",
                    producer="lc_classifier",
                    channel="alerce",
                ),
                right=PredicateLiteral(value="SN"),
            ),
            ComparisonPredicate(
                operator=">=",
                left=SemanticReference(
                    semantic_type="classification",
                    field_path="best.probability",
                    producer="lc_classifier",
                    channel="alerce",
                ),
                right=PredicateLiteral(value=0.8),
            ),
        ),
    )
    good = _portfolio(
        "good",
        [
            (
                "c-good",
                "classification@lc_classifier:alerce",
                {"best.class": "SN", "best.probability": 0.91},
            )
        ],
    )
    split_across_records = _portfolio(
        "split",
        [
            (
                "c-sn-low",
                "classification@lc_classifier:alerce",
                {"best.class": "SN", "best.probability": 0.4},
            ),
            (
                "c-agn-high",
                "classification@lc_classifier:alerce",
                {"best.class": "AGN", "best.probability": 0.95},
            ),
        ],
    )

    assert evaluate_portfolio_predicate(good, predicate) is True
    assert evaluate_portfolio_predicate(split_across_records, predicate) is False
    assert prune_portfolios((good, split_across_records), predicate) == (good,)


def test_taxon_tuple_is_residual_even_with_a_matching_provider_binding():
    endpoint = _endpoint()
    graph = CapabilityGraph(
        endpoint_capabilities=(endpoint,), payload_capabilities=(),
        field_mapping_capabilities=(), transform_capabilities=(), semantic_record_capabilities=(),
        request_constraint_capabilities=(RequestConstraintCapability(
            broker=endpoint.broker, origin=endpoint.origin, endpoint=endpoint.endpoint,
            parameter="kind", semantic_path="classification.best.taxon", operator="=",
        ),),
    )
    ref = SemanticReference(semantic_type="classification", field_path="best.taxon")
    literal = PredicateLiteral(value=(2220, 2242, 2246))
    for left, right in ((ref, literal), (literal, ref)):
        predicate = ComparisonPredicate(operator="=", left=left, right=right)
        realization = realize_predicate(predicate, endpoint=endpoint, graph=graph)
        assert realization.pushdown is None
        assert realization.residual == predicate
        assert realization.params == {}


def test_taxon_literal_is_strict_canonical_frozen_and_round_trips_json():
    import pytest
    from pydantic import ValidationError
    literal = PredicateLiteral(value=(2220, 2242, 2246))
    assert literal.model_dump(mode="json")["value"] == [2220, 2242, 2246]
    restored = PredicateLiteral.model_validate(literal.model_dump(mode="json"))
    assert restored == literal and hash(restored) == hash(literal)
    assert isinstance(restored.value, tuple)
    with pytest.raises(ValidationError):
        restored.value = (2222,)
    for invalid in ((), (2222, 2222), (2242, 2220), (True,), ("2222",), ["2222"], [True]):
        with pytest.raises(ValidationError):
            PredicateLiteral(value=invalid)
    predicate = ComparisonPredicate(operator="=", left=SemanticReference(
        semantic_type="classification", field_path="best.taxon"), right=literal)
    assert ComparisonPredicate.model_validate(predicate.model_dump(mode="json")) == predicate


def test_tuple_literals_are_rejected_outside_taxon_equality():
    import pytest
    from pydantic import ValidationError
    literal = PredicateLiteral(value=(2222,))
    for noun, field, operator in (
        ("summary", "best.taxon", "="), ("classification", "best.class", "="),
        ("classification", "best.taxon", "<"), ("classification", "best.taxon", ">="),
    ):
        reference = SemanticReference(semantic_type=noun, field_path=field)
        for left, right in ((reference, literal), (literal, reference)):
            with pytest.raises(ValidationError):
                ComparisonPredicate(operator=operator, left=left, right=right)
    with pytest.raises(ValidationError):
        ComparisonPredicate(operator="=", left=literal, right=literal)


def test_lowering_resolves_codes_without_changing_surface_words():
    from alertissimo.dsl.predicate_lowering import lower_expression_predicate, PredicateLoweringError
    import pytest
    text = 'classification.best.taxon = "  SuPeRnOvA  "'
    surface = parse_surface_script('objects ZTF20aaaaaaa from ztf via alerce\nwhere ' + text)
    before = surface.model_dump(mode="json")
    compiled = lower_surface(surface)
    assert surface.model_dump(mode="json") == before
    assert text in str(before)
    literals = [s.predicate.right.value for s in compiled.workflow.steps
                if isinstance(getattr(s, "predicate", None), ComparisonPredicate)]
    assert literals and all(v == (2220, 2242, 2246) for v in literals)
    for literal in ('2222', '"2222"', '"snia"'):
        assert lower_expression_predicate('classification.best.taxon = ' + literal,
                                          frozenset({"classification"})).right.value == (2222,)
    with pytest.raises(PredicateLoweringError, match="snia") as error:
        lower_expression_predicate('classification.best.taxon = "sniaa"', frozenset({"classification"}))
    assert "sniaa" in str(error.value)
    with pytest.raises(PredicateLoweringError, match="requires = or !="):
        lower_expression_predicate('classification.best.taxon < 3', frozenset({"classification"}))
