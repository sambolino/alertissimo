"""Collection admission through the real facade; controlled native payloads only."""
from copy import deepcopy
from dataclasses import replace
from itertools import count

import pytest

from alertissimo.api import execute_dsl, validate_dsl
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance
from alertissimo.data_layer.runtime.capability_graph import build_capability_graph
from alertissimo.data_layer.runtime.recipes import ConstantValueSource, RecipeParameter
from alertissimo.dsl import (
    SurfaceLoweringError, compile_surface_fragment, lower_surface,
    parse_surface_fragment, parse_surface_script,
)
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.orchestration.ir import (
    ConfirmStep, FilterStep, GetLightcurveStep, LookupStep, Source, TargetSelector, WorkflowIR,
)
from alertissimo.orchestration.normalization import summary_object_identity
from alertissimo.orchestration.planner import PlanningDeferredError, plan_workflow
from alertissimo.orchestration.runtime import WorkflowRun
from alertissimo.orchestration.validation import (
    SourceCapabilityResult, collection_workflow_issues, predicate_material_gaps,
    required_material_variants, validate_step_capabilities, validate_workflow_capabilities,
)

IDS = ('ZTF20aaaaaaa', 'ZTF20bbbbbbb')
LOOKUP = f'objects {", ".join(IDS)} from ztf via alerce\n'
GET = 'with lightcurve via fink\n'
LC = 'lightcurve@ztf:fink'
COUNT = f'count({LC}.points where photometry.g.psf.mag exists and photometry.g.upper_limit = false) >= 5'
EVERY = (f'for every {{filter}} in [g, r]: (count({LC}.points where '
         'photometry.{filter}.psf.mag exists and photometry.{filter}.upper_limit = false) >= 5)')


@pytest.fixture(scope='module')
def graph():
    return build_capability_graph()


@pytest.fixture(scope='module')
def paths():
    return SemanticPathModel.from_ontology()


def condition(text, paths):
    return lower_expression_predicate(text, paths.record_types, semantic_paths=paths, origins=('ztf',))


def identities(portfolios):
    return [summary_object_identity(p)[1] for p in portfolios]


class Executor:
    def __init__(self, *, fail_fink=False, missing_flags=False):
        self.calls, self.sequence = [], count()
        self.fail_fink, self.missing_flags = fail_fink, missing_flags

    def execute(self, broker, origin, endpoint, params=None, headers=None):
        assert headers is None and origin == 'ztf'
        params = deepcopy(dict(params or {}))
        self.calls.append((broker, endpoint, params))
        if broker == 'alerce' and endpoint == 'query_object':
            payload = {'oid': params['oid'], 'meanra': 10.0, 'meandec': 20.0,
                       'ndet': 10, 'firstmjd': 59000, 'lastmjd': 59002 if params['oid'] == IDS[1] else 59001}
        elif broker == 'alerce' and endpoint == 'query_objects':
            # B is most recent but has only four g witnesses. A must not refill it.
            payload = {'items': [{'oid': oid, 'meanra': 10.0, 'meandec': 20.0, 'ndet': 10,
                                  'firstmjd': 59000, 'lastmjd': 59002 if oid == IDS[1] else 59001}
                                 for oid in reversed(IDS)], 'total': 2}
        else:
            assert (broker, endpoint) == ('fink', 'objects'), self.calls[-1]
            if self.fail_fink:
                raise RuntimeError('controlled required history failure')
            payload = []
            for oid in params['objectId'].split(','):
                for band, number in ((1, 5 if oid == IDS[0] else 4), (2, 5)):
                    for index in range(number):
                        payload.append({'i:objectId': oid, 'i:candid': 10000 * (IDS.index(oid) + 1) + band * 100 + index,
                                        'i:jd': 2459000.5 + index, 'i:fid': band,
                                        'i:magpsf': 18.0, 'i:sigmapsf': 0.1, 'i:drb': 0.99,
                                        'i:ra': 10.0, 'i:dec': 20.0, 'i:ndethist': 10,
                                        'v:classification': 'SN candidate', 'd:snn_sn_vs_all': 0.99,
                                        **({} if self.missing_flags else {'d:tag': 'valid'})})
        return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
            internal_execution_id=InternalExecutionId(f'collection-admission:{next(self.sequence)}'),
            broker=broker, origin=origin, endpoint=endpoint, params=params,
        ))


@pytest.mark.parametrize('expression', [
    COUNT, EVERY, f'count({LC}.points) >= 10',
    f'for any {{filter}}: (min({LC}.points.photometry.{{filter}}.psf.mag) < 19)',
    f'max({LC}.points.photometry.g.psf.mag) < 19',
    'for any {output}: (classification.assessment.{output}.probability >= 0.8)',
])
def test_later_collection_filters_validate_and_plan_after_required_material(graph, expression):
    # max < 19 is admissible but still unknown on open completeness.
    source = LOOKUP + GET + 'filter ' + expression
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    assert result.compilation.workflow.dsl_version == 2
    plan = plan_workflow(result.compilation.workflow, graph)
    assert plan.steps[-1].endpoint_plans == ()
    assert plan.steps[-1].candidate_input_from.step_index == len(plan.steps) - 2


@pytest.mark.parametrize('expression', [COUNT, EVERY])
def test_public_filter_selects_witnessed_candidates_and_binds_only_survivors(graph, expression):
    executor = Executor()
    source = LOOKUP + GET + 'filter ' + expression + '\nwith classification via fink'
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert identities(result.portfolios) == [IDS[0]]
    fink = [params['objectId'].split(',') for broker, endpoint, params in executor.calls if broker == 'fink']
    assert fink[0] == list(IDS)
    assert fink[-1] == [IDS[0]]
    assert result.run.workflow.dsl_version == 2
    loaded = WorkflowRun.model_validate_json(result.run.model_dump_json())
    assert loaded == result.run
    assert len(result.result.steps[-2].portfolios) == 1


@pytest.mark.parametrize('expression', [
    f'count({LC}.points) = 10',
    f'count({LC}.points) = 0',
    f'min({LC}.points.photometry.g.psf.mag) > 17',
    f'for every {{filter}}: (count({LC}.points where photometry.{{filter}}.psf.mag exists) >= 5)',
])
def test_open_completeness_stays_unknown_through_the_public_facade(graph, expression):
    executor = Executor()
    result = execute_dsl(LOOKUP + GET + 'filter ' + expression, graph=graph,
                         executor=executor, continue_from=None)
    assert result.portfolios == ()
    assert len(result.result.steps[-2].portfolios) == 2  # Retain the input snapshot.


def test_missing_flag_values_do_not_become_false_after_admission(graph):
    result = execute_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph,
                         executor=Executor(missing_flags=True), continue_from=None)
    assert result.portfolios == ()


def test_continuation_uses_the_immutable_material_prefix_without_new_calls(graph):
    executor = Executor()
    first = execute_dsl(LOOKUP + GET, graph=graph, executor=executor, continue_from=None)
    before, calls = first.to_dict(), len(executor.calls)
    validation = validate_dsl('filter ' + EVERY, graph=graph, continue_from=first)
    assert validation.is_runnable, validation.lowering_error
    second = execute_dsl('filter ' + EVERY, graph=graph, executor=executor, continue_from=first)
    assert identities(second.portfolios) == [IDS[0]]
    assert len(executor.calls) == calls
    assert first.to_dict() == before
    assert second.run.steps[:len(first.run.steps)] == first.run.steps
    assert second.workflow.steps[:len(first.workflow.steps)] == first.workflow.steps
    assert second.workflow.dsl_version == first.workflow.dsl_version == 2


def test_later_filter_after_latest_does_not_refill_the_selected_population(graph):
    executor = Executor()
    source = ('objects from ztf via alerce\ninside (10, 20, 30arcsec)\nlatest 1\n'
              + GET + 'filter ' + COUNT)
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_runnable, validation.lowering_error
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert result.portfolios == ()
    assert [params['objectId'] for broker, _, params in executor.calls if broker == 'fink'] == [IDS[1]]
    assert identities(result.result.steps[0].portfolios) == [IDS[1]]


@pytest.mark.parametrize('tail', [
    'where ' + COUNT + '\nlatest 1\n' + GET,
    'latest 1\n' + GET + 'where ' + COUNT,
])
def test_initial_collection_latest_is_explicitly_deferred_to_item_4a(graph, tail):
    result = validate_dsl('objects from ztf via alerce\ninside (10, 20, 30arcsec)\n' + tail,
                          graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'item 4a' in str(result.lowering_error)
    assert result.capabilities.deferred


def test_initial_discovery_cannot_borrow_later_history_material(graph):
    source = 'objects from ztf via alerce\ninside (10, 20, 30arcsec)\nwhere ' + COUNT + '\n' + GET
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'item 4a' in str(result.lowering_error)


def test_future_retrieval_does_not_supply_an_earlier_filter(graph):
    result = validate_dsl(LOOKUP + 'filter ' + COUNT + '\n' + GET, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'item 4a' in str(result.lowering_error)
    assert 'before this step' in str(result.lowering_error)


@pytest.mark.parametrize('clause', ['where ' + COUNT, 'with lightcurve via fink where ' + COUNT])
def test_collection_propositions_in_confirm_are_rejected(graph, clause):
    result = validate_dsl(LOOKUP + clause + '\nconfirm by 1 via fink', graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'collection predicates in confirm' in str(result.lowering_error)
    assert result.capabilities.deferred[0].subject == 'confirm'


def test_bare_confirm_after_a_collection_filter_does_not_inherit_its_condition(graph):
    executor = Executor()
    result = execute_dsl(LOOKUP + GET + 'filter ' + COUNT + '\nconfirm by 1 via fink',
                         graph=graph, executor=executor, continue_from=None)
    assert identities(result.portfolios) == [IDS[0]]
    assert isinstance(result.workflow.steps[-1], ConfirmStep)
    assert result.workflow.steps[-1].predicate is None


def test_required_retrieval_failure_remains_a_workflow_failure(graph):
    from alertissimo.orchestration.runtime import WorkflowExecutionError
    with pytest.raises(WorkflowExecutionError, match='controlled required history failure'):
        execute_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph,
                    executor=Executor(fail_fink=True), continue_from=None)


def test_canonical_ir_cannot_bypass_material_or_confirmation_guards(graph, paths):
    predicate = condition(COUNT, paths)
    lookup = LookupStep(target=TargetSelector(kind='object', ids=[IDS[0]]),
                        sources=[Source(origin='ztf', broker='alerce')])
    filtered = FilterStep(predicate=predicate)
    no_material = WorkflowIR(steps=[lookup, filtered])
    assert validate_step_capabilities(filtered, graph).status == 'not_applicable'
    assert validate_workflow_capabilities(no_material, graph)[-1].status == 'deferred'
    with pytest.raises(PlanningDeferredError, match='item 4a'):
        plan_workflow(no_material, graph)
    material = GetLightcurveStep(sources=[Source(origin='ztf', broker='fink')])
    assert collection_workflow_issues(WorkflowIR(steps=[lookup, material, filtered]), graph) == ()
    plan_workflow(WorkflowIR(steps=[lookup, material, filtered]), graph)
    confirmed = ConfirmStep(predicate=predicate, sources=[Source(origin='ztf', broker='fink')])
    assert validate_step_capabilities(confirmed, graph).status == 'deferred'
    with pytest.raises(PlanningDeferredError, match='collection predicates in confirm'):
        plan_workflow(WorkflowIR(steps=[lookup, material, confirmed]), graph)


def test_version_one_continuations_refuse_collections_without_implicit_upgrade(graph):
    base = lower_surface(parse_surface_script(LOOKUP + GET), graph=graph).workflow
    legacy = WorkflowIR.model_validate({**base.model_dump(), 'dsl_version': 1})
    fragment = parse_surface_fragment('filter ' + COUNT)
    with pytest.raises(SurfaceLoweringError, match='dsl_version 2'):
        compile_surface_fragment(fragment, legacy, graph=graph)
    assert legacy.dsl_version == 1


def test_required_output_proof_excludes_optional_calls_and_nonprojected_fields(graph, paths):
    original, = graph.query_recipes(op='get_lightcurve', broker='fink', origin='ztf')
    primary, = original.calls
    flags = tuple(field for field in primary.outputs if field.relative_field_path.endswith('.upper_limit'))
    assert flags
    thin = replace(primary, outputs=tuple(field for field in primary.outputs if field not in flags))
    optional = replace(primary, required=False, outputs=flags)
    recipe = replace(original, calls=(thin, optional))
    endpoint = next(item for item in graph.endpoint_capabilities
                    if (item.broker, item.origin, item.endpoint) == ('fink', 'ztf', primary.endpoint))
    source = SourceCapabilityResult(Source(origin='ztf', broker='fink'), 'supported', (endpoint,),
                                    'synthetic optional-proof case', (recipe,))
    predicate = condition(COUNT, paths)
    variants = required_material_variants(source, graph)
    assert len(variants) == 1
    assert any('upper_limit' in gap for gap in predicate_material_gaps(predicate, variants[0], broker='fink'))
    # Endpoint-wide mappings cannot supply a field omitted by the required call.
    graph_without_flag = replace(graph, recipe_capabilities=tuple(
        replace(item, calls=(thin,)) if item == original else item for item in graph.recipe_capabilities))
    result = validate_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph_without_flag, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'upper_limit' in str(result.lowering_error)
    projected_endpoint = replace(endpoint, supports_projection=True, projection_param='columns')
    projected_graph = replace(graph, endpoint_capabilities=tuple(
        projected_endpoint if item == endpoint else item for item in graph.endpoint_capabilities))
    projected_call = replace(primary, params=primary.params + (
        RecipeParameter(parameter='columns', source=ConstantValueSource(value='i:objectId')),
    ))
    projected_source = replace(source, recipes=(replace(original, calls=(projected_call,)),))
    outputs, = required_material_variants(projected_source, projected_graph)
    assert predicate_material_gaps(predicate, outputs, broker='fink')


def test_one_incomplete_alternative_route_cannot_borrow_another_routes_fields(graph):
    original, = graph.query_recipes(op='get_lightcurve', broker='fink', origin='ztf')
    primary, = original.calls
    thin = replace(primary, outputs=tuple(field for field in primary.outputs
                                        if not field.relative_field_path.endswith('.upper_limit')))
    alternative = replace(original, alternative_index=original.alternative_index + 1, calls=(thin,))
    graph = replace(graph, recipe_capabilities=graph.recipe_capabilities + (alternative,))
    result = validate_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'upper_limit' in str(result.lowering_error)


def test_future_product_does_not_make_an_earlier_unqualified_filter_ambiguous(graph):
    source = LOOKUP + GET + 'filter count(lightcurve.points) >= 5\nwith lightcurve via alerce'
    result = validate_dsl(source, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    # Canonical validation retains that occurrence order through JSON too.
    restored = WorkflowIR.model_validate_json(result.compilation.workflow.model_dump_json())
    assert restored == result.compilation.workflow


def test_continuation_static_product_ambiguity_includes_the_inherited_prefix(graph):
    base = lower_surface(parse_surface_script(LOOKUP + GET + 'with lightcurve via lasair'), graph=graph).workflow
    fragment = parse_surface_fragment('filter count(lightcurve.points) >= 5')
    from alertissimo.dsl import validate_surface_fragment_semantics
    report = validate_surface_fragment_semantics(fragment, base)
    assert not report.is_valid
    assert any('qualify' in issue.message for issue in report.errors)
    with pytest.raises(SurfaceLoweringError, match='qualify'):
        compile_surface_fragment(fragment, base, graph=graph)


def test_lookup_initial_where_can_use_its_scheduled_implicit_retrieval(graph):
    # Existing lookup lowering requests named material before its initial filter.
    result = validate_dsl(LOOKUP + 'where ' + COUNT, graph=graph, continue_from=None)
    assert result.is_valid and result.is_runnable, result.lowering_error
    assert [step.op for step in result.compilation.workflow.steps] == ['lookup', 'get_lightcurve', 'filter']
    assert result.compilation.workflow.steps[1].sources == [Source(origin='ztf', broker='fink')]
    from alertissimo.orchestration.ir.predicates import iter_semantic_references
    references = tuple(iter_semantic_references(result.compilation.workflow.steps[-1].predicate))
    assert {(ref.producer, ref.channel) for ref in references} == {('ztf', 'fink')}


def test_runtime_ambiguity_is_visible_through_the_public_facade(graph, monkeypatch):
    import alertissimo.orchestration.pipeline as pipeline
    from alertissimo.data_layer.representations import InternalRecordId
    normalizer = pipeline.normalize_execution

    def competing_version(execution, **kwargs):
        portfolios = normalizer(execution, **kwargs)
        if execution.execution_provenance.broker != 'fink':
            return portfolios
        result = []
        for portfolio in portfolios:
            product = next(record for record in portfolio.records if record.semantic_type == LC)
            another = replace(product, internal_record_id=InternalRecordId(product.internal_record_id.value + ':v2'),
                              fields={**product.fields, 'provenance.producer.version': 'synthetic-v2'})
            result.append(replace(portfolio, records=portfolio.records + (another,)))
        return tuple(result)

    monkeypatch.setattr(pipeline, 'normalize_execution', competing_version)
    executor = Executor()
    result = execute_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph,
                         executor=executor, continue_from=None)
    assert result.portfolios == ()
    warnings = result.run.steps[-1].warnings
    assert len(warnings) == 2 and all('ambiguous_product' in warning for warning in warnings)
    assert all(any(oid in warning for warning in warnings) for oid in IDS)
    assert WorkflowRun.model_validate_json(result.run.model_dump_json()).steps[-1].warnings == warnings
    assert result.to_dict()['run']['steps'][-1]['warnings'] == list(warnings)
    before, calls = result.to_dict(), len(executor.calls)
    continued = execute_dsl('with classification via fink', graph=graph, executor=executor, continue_from=result)
    assert continued.portfolios == () and len(executor.calls) == calls
    assert continued.run.steps[:len(result.run.steps)] == result.run.steps
    assert result.to_dict() == before
    assert continued.run.steps[len(result.run.steps) - 1].warnings == warnings
    # A scientific diagnostic must never exempt a genuine acquisition warning.
    from alertissimo.orchestration.incremental import IncrementalExecutionError, _require_extension_prefix
    bad = result.run.steps[-1].model_copy(update={'warnings': warnings + ('supplementary retrieval incomplete',)})
    bad_run = result.run.model_copy(update={'steps': result.run.steps[:-1] + (bad,)})
    bad_prefix = replace(result.staged, execution=replace(result.staged.execution, run=bad_run))
    with pytest.raises(IncrementalExecutionError, match='incomplete supplementary'):
        _require_extension_prefix(bad_prefix, plan_workflow(result.workflow, graph))


@pytest.mark.parametrize('source', [
    LOOKUP + 'filter ' + COUNT + '\n' + GET,
    LOOKUP + 'where ' + COUNT + '\nconfirm by 1 via fink',
    'objects from ztf via alerce\ninside (10, 20, 30arcsec)\nlatest 1\nwhere ' + COUNT,
])
def test_rejected_collection_programs_make_no_provider_calls(graph, source):
    executor = Executor()
    with pytest.raises(SurfaceLoweringError):
        execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert executor.calls == []


def test_initial_where_without_latest_can_use_required_discovery_witnesses(graph):
    class ConeExecutor(Executor):
        def execute(self, broker, origin, endpoint, params=None, headers=None):
            assert (broker, origin, endpoint) == ('fink', 'ztf', 'conesearch')
            assert headers is None
            self.calls.append((broker, endpoint, dict(params or {})))
            payload = [{'i:objectId': oid, 'i:candid': index + 1, 'i:jd': 2459000.5,
                        'i:ra': 10.0, 'i:dec': 20.0, 'i:fid': 1, 'i:magpsf': 18.0,
                        'i:drb': 0.99 if oid == IDS[0] else 0.1}
                       for index, oid in enumerate(IDS)]
            return ExecutionResult(payload=payload, execution_provenance=InternalExecutionProvenance(
                InternalExecutionId('collection-cone'), broker, origin, endpoint, dict(params or {})))
    expression = 'count(measurement@ztf:fink where quality.real_bogus >= 0.8) >= 1'
    source = 'objects from ztf via fink\ninside (10, 20, 30arcsec)\nwhere ' + expression
    validation = validate_dsl(source, graph=graph, continue_from=None)
    assert validation.is_valid and validation.is_runnable, validation.lowering_error
    plans = plan_workflow(validation.compilation.workflow, graph)
    assert plans.steps[0].endpoint_plans[0].predicate_realization.pushdown is None
    executor = ConeExecutor()
    result = execute_dsl(source, graph=graph, executor=executor, continue_from=None)
    assert identities(result.portfolios) == [IDS[0]]
    assert len(executor.calls) == 1


def test_discovery_residual_ambiguity_reaches_existing_warnings_in_each_phase(paths):
    from alertissimo.data_layer.representations import (
        InternalPortfolioId, InternalRecordId, Portfolio, SemanticRecord,
    )
    from alertissimo.orchestration.ir import ConeSearchStep
    from alertissimo.orchestration.normalization import normalize_workflow_execution
    from alertissimo.orchestration.pipeline import (
        _candidate_view_from_step, _candidate_view_from_plan_executions,
    )
    from alertissimo.orchestration.runtime import (
        EndpointPlan, PredicateRealization, StepExecutionResult, StepRun, StepRunState, WorkflowExecutionResult,
    )
    predicate = condition(COUNT, paths)
    data = Portfolio(InternalPortfolioId('two-products'), records=(
        SemanticRecord(InternalRecordId('identity'), 'summary@ztf:fink', {'identity.object_id': IDS[0]}),
        *(SemanticRecord(InternalRecordId(f'lc-{version}'), LC, {'points': ()}) for version in (1, 2)),
    ))
    execution = ExecutionResult(payload=[], execution_provenance=InternalExecutionProvenance(
        InternalExecutionId('discovery-proof'), 'fink', 'ztf', 'conesearch'))
    cache = {'discovery-proof': (data,)}
    step = ConeSearchStep(semantic_type='summary', ra=10, dec=20, radius=30, predicate=predicate,
                          sources=[Source(origin='ztf', broker='fink')])
    plan = EndpointPlan(broker='fink', origin='ztf', endpoint='conesearch',
                        predicate_realization=PredicateRealization(residual=predicate))
    occurrence = StepRun(step_index=0, state=StepRunState.SUCCEEDED, endpoint_plans=(plan,),
                         execution_ids=('discovery-proof',))
    raw = StepExecutionResult(0, (execution,))
    run = WorkflowRun(workflow=WorkflowIR(steps=[step]), steps=(occurrence,))
    normalized = normalize_workflow_execution(WorkflowExecutionResult(run, (raw,)),
                                               normalized_execution_cache=cache)
    assert normalized.steps[0].portfolios == ()
    warnings = normalized.run.steps[0].warnings
    assert len(warnings) == 1 and 'ambiguous_product' in warnings[0]
    for early in (False, True):
        messages = []
        if early:
            view = _candidate_view_from_plan_executions(occurrence, 0, (execution,),
                normalized_execution_cache=cache, validate_semantic_model=True, diagnostics=messages)
        else:
            view = _candidate_view_from_step(occurrence, raw,
                normalized_execution_cache=cache, validate_semantic_model=True, diagnostics=messages)
        assert view.portfolios == ()
        assert messages == list(warnings)


def test_another_brokers_material_cannot_supply_a_qualified_collection(graph):
    lasair_condition = COUNT.replace('lightcurve@ztf:fink', 'lightcurve@ztf:lasair')
    result = validate_dsl(LOOKUP + GET + 'filter ' + lasair_condition, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'item 4a' in str(result.lowering_error)
    assert 'lightcurve@ztf:lasair' in str(result.lowering_error)


@pytest.mark.parametrize('producer', ['custom_model', 'lsst'])
def test_implicit_collection_retrieval_does_not_drop_an_unrepresented_producer(graph, producer):
    expression = COUNT.replace('lightcurve@ztf:fink', f'lightcurve@{producer}:fink')
    result = validate_dsl(LOOKUP + 'where ' + expression, graph=graph, continue_from=None)
    assert result.is_valid and not result.is_runnable
    assert 'unrepresentable_producer_constraint' in str(result.lowering_error)


def test_multi_origin_implicit_collection_request_retains_its_producer():
    from alertissimo.dsl.lowering import _implicit_requirements_from_where
    from alertissimo.dsl.surface import WhereClause
    surface = parse_surface_script('objects from ztf, lsst via fink\nwhere ' + COUNT)
    paths = SemanticPathModel.from_ontology()
    where = next(clause for clause in surface.clauses if isinstance(clause, WhereClause))
    requests = _implicit_requirements_from_where(surface, where, record_types=paths.record_types)
    assert requests and all(request.source == 'ztf' and request.via == 'fink' for request in requests)


def test_collection_where_capabilities_match_the_requests_in_canonical_lowering(graph):
    from alertissimo.dsl import validate_surface_capabilities
    implicit_source = LOOKUP + 'where ' + COUNT
    surface = parse_surface_script(implicit_source)
    report = validate_surface_capabilities(surface, graph=graph)
    assert report.is_supported, report
    requests = tuple(check for check in report.checks if check.subject == 'requirement')
    assert requests and all(check.semantic_noun == 'lightcurve' for check in requests)
    assert all(check.producer is None and check.origin == 'ztf' and check.broker == 'fink'
               for check in requests)
    implicit = validate_dsl(implicit_source, graph=graph, continue_from=None)
    explicit = validate_dsl(LOOKUP + GET + 'filter ' + COUNT, graph=graph, continue_from=None)
    assert implicit.is_runnable, implicit.lowering_error
    assert explicit.is_runnable, explicit.lowering_error
    assert implicit.compilation.workflow == explicit.compilation.workflow
