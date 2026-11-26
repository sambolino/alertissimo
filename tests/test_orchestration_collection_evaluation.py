"""Scientific counterexamples for collections, using synthetic offline evidence.

Completeness inputs here are invented test proofs, never route declarations.
Public workflow execution remains gated until the separate admission slice.
"""
from dataclasses import replace
from functools import lru_cache
from itertools import product

import pytest

from alertissimo.data_layer.representations import (
    InternalPortfolioId, InternalRecordId, Portfolio, SemanticRecord,
)
from alertissimo.data_layer.semantic_model import SemanticPathModel
from alertissimo.dsl.predicate_lowering import lower_expression_predicate
from alertissimo.orchestration.ir.predicates import NotPredicate, QuantifierPredicate
from alertissimo.orchestration.normalization import ExecutionPortfolioResult, StepPortfolioResult
from alertissimo.orchestration.normalization.normalize import (
    filter_execution_groups, normalize_workflow_execution,
)
from alertissimo.orchestration.normalization.predicate import (
    evaluate_portfolio_predicate, evaluate_portfolio_predicate_truth, prune_portfolios,
)
from alertissimo.orchestration.pipeline import _filter_view

LC = 'lightcurve@ztf:fink'
CLASS = 'classification@lc_classifier:alerce'
ABSENT = object()


@lru_cache(maxsize=1)
def paths():
    return SemanticPathModel.from_ontology()


@lru_cache(maxsize=128)
def predicate(text, origin='ztf'):
    return lower_expression_predicate(text, paths().record_types, semantic_paths=paths(), origins=(origin,))


def candidate(*rows, origin='ztf', name='candidate'):
    return Portfolio(
        internal_portfolio_id=InternalPortfolioId(name),
        records=tuple(SemanticRecord(
            internal_record_id=InternalRecordId(f'{name}:{index}'), semantic_type=kind, fields=fields,
        ) for index, (kind, fields) in enumerate([
            (f'summary@{origin}:fink', {'identity.object_id': 'object-1', 'detection_count': 100000}),
            *rows,
        ])),
    )


def curve(points, *, forced=ABSENT, kind=LC):
    fields = {'points': tuple(points)}
    if forced is not ABSENT:
        fields['forced_photometry_points'] = tuple(forced)
    return kind, fields


def point(band='g', mag=18.5, limit=False, score=0.9, *, nested=False):
    fields = {f'photometry.{band}.psf.mag': mag, 'time.mjd': 60000.0}
    if limit is not ABSENT:
        fields[f'photometry.{band}.upper_limit'] = limit
    if score is not ABSENT:
        fields['quality.real_bogus'] = score
    if nested:
        fields = {'photometry': {band: {'psf': {'mag': mag}, **(
            {} if limit is ABSENT else {'upper_limit': limit})}}, 'time': {'mjd': 60000.0}}
    return fields


def proof(p, bands=('g', 'r', 'i'), *, field='points', record=1, complete=True):
    return {(p.records[record].internal_record_id.value, field): (complete, frozenset(bands))}


def truth(p, text, evidence=None, diagnostics=None, *, origin='ztf'):
    return evaluate_portfolio_predicate_truth(
        p, predicate(text, origin), collection_evidence=evidence, diagnostics=diagnostics,
    )


def test_default_six_band_domain_short_band_is_unknown_until_complete():
    points = [point(band) for band, n in zip('ugrizy', (5, 5, 5, 5, 5, 4)) for _ in range(n)]
    p = candidate(curve(points, kind='lightcurve@lsst:fink'), origin='lsst')
    text = ('for every {filter}: (count(lightcurve.points where '
            'photometry.{filter}.psf.mag exists) >= 5)')
    assert truth(p, text, origin='lsst') is None
    assert truth(p, text, proof(p, 'ugrizy'), origin='lsst') is False
    # Complete response size, summary counts and observed bands prove neither completeness nor domain.
    assert truth(p, text, proof(p, 'ugrizy', complete=False), origin='lsst') is None


@pytest.mark.parametrize('known,expected', [(5, True), (4, None)])
def test_count_range_includes_unknown_members_and_unseen_members(known, expected):
    p = candidate(curve([point() for _ in range(known)] + [point(score=ABSENT)]))
    text = f'count({LC}.points where quality.real_bogus >= 0.8)'
    assert truth(p, text + ' >= 5') is expected
    assert truth(p, text + ' >= 5', proof(p)) is expected
    assert truth(p, text + ' = 5', proof(p)) is None
    assert truth(p, text + ' = 5') is None
    if known == 5:
        assert truth(p, text + ' <= 4') is False
        assert truth(p, 'not (' + text + ' >= 5)') is False


@pytest.mark.parametrize('op,value,open_result,closed_result', [
    ('=', 2, None, True), ('!=', 2, None, False),
    ('<', 2, False, False), ('<=', 2, None, True),
    ('>', 2, None, False), ('>=', 2, True, True),
    ('=', 1, False, False), ('!=', 1, True, True),
    ('=', 2.5, False, False), ('!=', 2.5, True, True),
    ('<', 2.5, None, True), ('>=', 2.5, None, False),
])
def test_all_count_comparisons_use_integer_ranges(op, value, open_result, closed_result):
    p = candidate(curve([point(), point()]))
    expression = f'count({LC}.points) {op} {value}'
    assert truth(p, expression) is open_result
    assert truth(p, expression, proof(p)) is closed_result
    inverse = {'=': '=', '!=': '!=', '<': '>', '<=': '>=', '>': '<', '>=': '<='}[op]
    assert truth(p, f'{value} {inverse} count({LC}.points)', proof(p)) is closed_result


@pytest.mark.parametrize('rows', [(), (curve([]),), ((LC, {}),)])
def test_no_material_or_open_empty_is_not_zero(rows):
    p = candidate(*rows)
    assert truth(p, f'count({LC}.points) = 0') is None
    assert truth(p, f'count({LC}.points) >= 0') is True
    assert truth(p, f'count({LC}.points) < 0') is False
    assert truth(p, f'min({LC}.points.time.mjd) < 1') is None


def test_only_explicit_applicable_evidence_closes_the_exact_array():
    p = candidate(curve([], forced=[]))
    assert truth(p, f'count({LC}.points) = 0', proof(p)) is True
    assert truth(p, f'count({LC}.forced_photometry_points) = 0', proof(p)) is None
    assert truth(p, f'count({LC}.points) = 0', proof(p, field='other')) is None
    malformed = candidate((LC, {'points': None}))
    assert truth(malformed, f'count({LC}.points) = 0', proof(malformed)) is None


@pytest.mark.parametrize('function,relation,threshold,result', [
    ('min', '<', 19, True), ('min', '>', 19, False),
    ('min', '>', 18, None), ('min', '=', 18.5, None),
    ('max', '>', 18, True), ('max', '<', 18, False),
    ('max', '<', 19, None), ('max', '=', 18.5, None),
])
def test_extrema_with_a_known_value_and_unknown_value(function, relation, threshold, result):
    p = candidate(curve([point(), point(mag=None)]))
    text = f'{function}({LC}.points.photometry.g.psf.mag) {relation} {threshold}'
    assert truth(p, text) is result
    assert truth(p, text, proof(p)) is result


@pytest.mark.parametrize('function', ['min', 'max'])
def test_complete_empty_extremum_is_unknown_and_never_zero(function):
    p = candidate(curve([]))
    for suffix in (' = 0', ' != 0', ' < 100', ' >= 0'):
        expression = f'{function}({LC}.points.photometry.g.psf.mag)' + suffix
        assert truth(p, expression, proof(p)) is None
        assert truth(p, f'not ({expression})', proof(p)) is None


@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), True, '18.5'])
def test_invalid_extremum_value_is_unknown(value):
    p = candidate(curve([point(mag=value)]))
    assert truth(p, f'min({LC}.points.photometry.g.psf.mag) < 19', proof(p)) is None


def test_complete_known_extrema_and_negative_flux_do_not_get_reinterpreted():
    p = candidate(curve([point(mag=20), point(mag=21)]))
    assert truth(p, f'min({LC}.points.photometry.g.psf.mag) > 19') is None
    assert truth(p, f'min({LC}.points.photometry.g.psf.mag) > 19', proof(p)) is True
    assert truth(p, f'max({LC}.points.photometry.g.psf.mag) = 21', proof(p)) is True
    flux_only = candidate(curve([{'photometry.g.psf.flux': -5.0}]))
    assert truth(flux_only, f'min({LC}.points.photometry.g.psf.mag) < 19') is None


@pytest.mark.parametrize('nested', [False, True])
def test_branch_membership_is_not_shared_across_bands_even_under_not(nested):
    p = candidate(curve([point('g', nested=nested)]))
    assert truth(p, f'count({LC}.points where photometry.r.upper_limit != true) >= 1') is None
    assert truth(p, f'count({LC}.points where not (photometry.r.upper_limit = true)) = 0', proof(p)) is True
    assert truth(p, f'count({LC}.points where photometry.g.upper_limit = false) = 1', proof(p)) is True
    assert truth(p, f'min({LC}.points.photometry.r.psf.mag) < 19', proof(p)) is None


def test_missing_leaf_in_present_branch_is_unknown_but_other_band_is_not_a_member():
    p = candidate(curve([point('g'), {'photometry.r.upper_limit': False}]))
    expression = f'count({LC}.points where photometry.r.psf.mag < 19)'
    assert truth(p, expression + ' >= 1', proof(p)) is None
    assert truth(p, expression + ' > 1', proof(p)) is False
    assert truth(p, expression + ' = 0', proof(p)) is None


def test_no_implicit_censoring_or_quality_policy_and_missing_flags_stay_unknown():
    p = candidate(curve([point(mag=None, limit=True), point(mag=18, limit=ABSENT), point(mag=20, score=0.1)]))
    expression = f'count({LC}.points where photometry.g.psf.mag exists and photometry.g.upper_limit = false)'
    assert truth(p, expression + ' = 1', proof(p)) is None
    assert truth(p, expression + ' >= 1') is True
    # No automatic score threshold: the explicitly non-limit, faint point is counted.
    assert truth(p, f'count({LC}.points where photometry.g.upper_limit = false) >= 1') is True
    # A bright limiting depth alone is no measured magnitude or qualifying detection.
    only_limit = candidate(curve([{'photometry.g.limit.mag': 17, 'photometry.g.upper_limit': True}]))
    assert truth(only_limit, expression + ' >= 1', proof(only_limit)) is False
    # If an explicit magnitude is present on a limit, extrema do not silently discard it.
    supplied_mag = candidate(curve([point(mag=17, limit=True)]))
    assert truth(supplied_mag, f'min({LC}.points.photometry.g.psf.mag) < 19') is True
    assert truth(supplied_mag, expression + ' >= 1', proof(supplied_mag)) is False


def test_delivered_bands_are_not_inferred_and_explicit_domain_restriction_is_respected():
    p = candidate(curve([point(band) for band in ('g', 'r') for _ in range(5)]))
    body = f'count({LC}.points where photometry.{{filter}}.psf.mag exists) >= 5'
    assert truth(p, 'for every {filter}: (' + body + ')') is None
    assert truth(p, 'for every {filter}: (' + body + ')', proof(p)) is False
    assert truth(p, 'for every {filter}: (' + body + ')', proof(p, ('g', 'r'))) is None
    assert truth(p, 'for every {filter} in [g, r]: (' + body + ')') is True
    absent = f'count({LC}.points where photometry.i.psf.mag exists) = 0'
    assert truth(p, absent, proof(p, ('g', 'r'))) is None
    assert truth(p, absent, proof(p)) is True


@pytest.mark.parametrize('left,right', list(product((True, False, None), repeat=2)))
def test_kleene_quantifier_truth_tables_and_exact_not_duality(left, right):
    # min < 19: true has a witness, false needs complete values, unknown has a missing value.
    points = [point(band, mag=(18 if result is True else 20 if result is False else None))
              for band, result in (('g', left), ('r', right))]
    p = candidate(curve(points))
    body = f'min({LC}.points.photometry.{{filter}}.psf.mag) < 19'
    expected_any = True if True in (left, right) else None if None in (left, right) else False
    expected_every = False if False in (left, right) else None if None in (left, right) else True
    for quantifier, dual, expected in (('any', 'every', expected_any), ('every', 'any', expected_every)):
        condition = predicate(f'for {quantifier} {{filter}} in [g, r]: ({body})')
        negated = NotPredicate(operand=condition)
        dual_form = QuantifierPredicate(quantifier=dual, parameter='filter', values=('g', 'r'),
                                       operand=NotPredicate(operand=condition.operand))
        kwargs = {'collection_evidence': proof(p)}
        assert evaluate_portfolio_predicate_truth(p, condition, **kwargs) is expected
        expected_not = None if expected is None else not expected
        assert evaluate_portfolio_predicate_truth(p, negated, **kwargs) is expected_not
        assert evaluate_portfolio_predicate_truth(p, dual_form, **kwargs) is expected_not


def test_output_domains_bind_one_record_and_never_cross_versions():
    p = candidate((CLASS, {'assessment.SN.class': 'SN', 'assessment.SN.probability': 0.2}),
                  (CLASS, {'assessment.SN.class': 'AGN', 'assessment.SN.probability': 0.99}))
    assert truth(p, 'for any {output}: (classification.assessment.{output}.probability >= 0.8)') is True
    split = ('for any {output}: (classification.assessment.{output}.class = "SN" and '
             'classification.assessment.{output}.probability >= 0.8)')
    assert truth(p, split) is False
    for quantifier in ('any', 'every'):
        messages = []
        text = f'for {quantifier} {{output}}: ({CLASS}.assessment.{{output}}.probability >= 0.8)'
        assert truth(p, text, diagnostics=messages) is None
        assert len(messages) == 1 and 'ambiguous_product' in messages[0]
    one = candidate((CLASS, {'assessment': {'SN': {'probability': 0.9}, 'AGN': {'probability': 0.2}}}))
    assert truth(one, f'for any {{output}}: ({CLASS}.assessment.{{output}}.probability >= 0.8)') is True
    assert truth(one, f'for every {{output}}: ({CLASS}.assessment.{{output}}.probability >= 0.8)') is False


@pytest.mark.parametrize('rows', [(), ((CLASS, {}),)])
@pytest.mark.parametrize('quantifier', ['any', 'every'])
def test_empty_data_derived_domain_and_its_negation_are_unknown(rows, quantifier):
    p = candidate(*rows)
    text = f'for {quantifier} {{output}}: ({CLASS}.assessment.{{output}}.probability > 0.5)'
    assert truth(p, text) is None
    assert truth(p, f'not ({text})') is None


def test_count_record_condition_output_domain_stays_on_its_element():
    p = candidate((CLASS, {'assessment.SN.probability': 0.9}),
                  (CLASS, {'assessment.AGN.probability': 0.1}))
    expression = ('count(classification where for any {output}: '
                  '(assessment.{output}.probability >= 0.8))')
    assert truth(p, expression + ' >= 1') is True
    assert truth(p, expression + ' >= 2') is None
    assert truth(p, expression + ' = 1') is None


def test_multiple_products_never_pool_or_pick_first_even_with_complete_test_proofs():
    p = candidate(curve([point()] * 4), curve([point()] * 5))
    for expression in (f'count({LC}.points) >= 5', f'min({LC}.points.photometry.g.psf.mag) < 19'):
        messages = []
        evidence = {**proof(p, record=1), **proof(p, record=2)}
        assert truth(p, expression, evidence, messages) is None
        assert not evaluate_portfolio_predicate(p, predicate(expression), diagnostics=messages)
        assert len(messages) == 1 and 'matches=2' in messages[0]
    qualified = candidate(curve([point()] * 5), curve([point()] * 4, kind='lightcurve@ztf:lasair'))
    assert truth(qualified, f'count({LC}.points) >= 5') is True
    assert truth(qualified, 'count(lightcurve.points) >= 5') is None


def test_point_arrays_and_incidental_measurements_count_separately_and_stay_open():
    p = candidate(curve([point()] * 2, forced=[{'forced_photometry.g.psf.mag': 20.0}] * 3),
                  ('measurement@ztf:fink', point()), ('measurement@ztf:fink', point()))
    assert truth(p, f'count({LC}.points) = 2', proof(p)) is True
    assert truth(p, f'count({LC}.forced_photometry_points) = 3', proof(p, field='forced_photometry_points')) is True
    assert truth(p, 'count(measurement@ztf:fink) >= 2') is True
    assert truth(p, 'count(measurement@ztf:fink) >= 4') is None
    assert truth(p, 'count(measurement@ztf:fink) = 2', proof(p)) is None


def test_material_audit_projection_does_not_reevaluate_partial_physical_products():
    p = candidate(curve([point()] * 5))
    raw = candidate(name='raw')  # Same object; physical call alone does not contain the array.
    source = StepPortfolioResult(step_index=0, executions=(
        ExecutionPortfolioResult(execution_id='physical', portfolios=(raw,)),
    ), materialized_portfolios=(p,))
    condition = predicate(f'count({LC}.points) >= 5')
    assert filter_execution_groups(source, condition, (p,))[0].portfolios == (raw,)
    assert prune_portfolios((raw,), condition) == ()
    assert source.portfolios == (p,)  # Immutable input snapshot.
    from alertissimo.orchestration.ir import FilterStep
    assert _filter_view(FilterStep(predicate=condition), 1, source).executions[0].portfolios == (raw,)


def test_ambiguity_warning_survives_rejection_run_serialization_and_replay():
    from alertissimo.orchestration.ir import FilterStep, LookupStep, TargetSelector, WorkflowIR
    from alertissimo.orchestration.runtime import (
        CandidateInputRef, StepExecutionResult, StepRun, StepRunState, WorkflowExecutionResult, WorkflowRun,
    )
    p = candidate(curve([point()] * 5), curve([point()] * 5))
    condition = predicate(f'count({LC}.points) >= 5')
    source = StepPortfolioResult(step_index=0, executions=(), materialized_portfolios=(p,))
    workflow = WorkflowIR(steps=[LookupStep(target=TargetSelector(kind='object', ids=['object-1'])),
                                 FilterStep(predicate=condition)])
    run = WorkflowRun(workflow=workflow, steps=(
        StepRun(step_index=0, state=StepRunState.SUCCEEDED),
        StepRun(step_index=1, state=StepRunState.SUCCEEDED,
                candidate_input_from=CandidateInputRef(step_index=0), warnings=('existing warning', 'existing warning')),
    ))
    physical = WorkflowExecutionResult(run=run, steps=(StepExecutionResult(0, ()), StepExecutionResult(1, ())))
    normalized = normalize_workflow_execution(physical, preserved_steps=(source,))
    assert normalized.steps[1].portfolios == ()
    assert normalized.run.steps[1].warnings[:2] == ('existing warning', 'existing warning')
    assert len(normalized.run.steps[1].warnings) == 3
    assert 'ambiguous_product' in normalized.run.steps[1].warnings[2]
    assert run.steps[1].warnings == ('existing warning', 'existing warning')
    loaded = WorkflowRun.model_validate_json(normalized.run.model_dump_json())
    assert loaded.steps[1].warnings == normalized.run.steps[1].warnings
    replay = normalize_workflow_execution(replace(physical, run=loaded), preserved_steps=(source,))
    assert replay.run.steps[1].warnings == normalized.run.steps[1].warnings
    diagnostics = []
    assert _filter_view(workflow.steps[1], 1, source, diagnostics=diagnostics).portfolios == ()
    assert diagnostics == [normalized.run.steps[1].warnings[2]]


def test_scalar_not_keeps_existential_record_semantics():
    p = candidate((CLASS, {'best.class': 'SN'}), (CLASS, {'best.class': 'AGN'}))
    assert truth(p, f'{CLASS}.best.class = "SN"') is True
    assert truth(p, f'not ({CLASS}.best.class = "SN")') is True
    assert truth(p, f'{CLASS}.best.probability >= 0.8') is None
    assert truth(p, f'not ({CLASS}.best.probability >= 0.8)') is None


def test_inner_filter_domain_membership_precedes_negated_condition():
    p = candidate(curve([point('g')]))
    expression = (f'count({LC}.points where for any {{filter}} in [r]: '
                  '(not (photometry.{filter}.upper_limit = true))) = 0')
    assert truth(p, expression, proof(p)) is True


def test_negated_output_existence_remains_on_the_bound_assertion():
    # Literal DSL path components normalize to lowercase. Keep the output key
    # lowercase too; the class label is a separate, case-preserved value.
    p = candidate((CLASS, {'assessment.sn.class': 'SN'}),
                  (CLASS, {'assessment.sn.probability': 0.9}))
    expression = ('for any {output}: '
                  '(not (classification.assessment.{output}.probability exists))')
    assert truth(p, expression) is True
    # Existing scalar NOT EXISTS still asks about the complete current view.
    assert truth(p, 'not (classification.assessment.sn.probability exists)') is False


def test_quantified_output_case_and_canonical_scalar_absence_keep_their_scope():
    from alertissimo.orchestration.ir.predicates import ExistsPredicate, SemanticReference
    p = candidate((CLASS, {'assessment.SN.class': 'SN'}),
                  (CLASS, {'assessment.SN.probability': 0.9}))
    expression = ('for any {output}: '
                  '(not (classification.assessment.{output}.probability exists))')
    # Runtime domains retain delivered case; they are not literal surface paths.
    assert truth(p, expression) is True
    explicit = NotPredicate(operand=ExistsPredicate(reference=SemanticReference(
        semantic_type='classification', field_path='assessment.SN.probability')))
    assert evaluate_portfolio_predicate_truth(p, explicit) is False


def test_output_fields_never_mix_between_outputs_in_one_record():
    p = candidate((CLASS, {'assessment.SN.class': 'SN', 'assessment.SN.probability': 0.1,
                          'assessment.AGN.class': 'AGN', 'assessment.AGN.probability': 0.99}))
    expression = ('for any {output}: (classification.assessment.{output}.class = "SN" '
                  'and classification.assessment.{output}.probability >= 0.8)')
    assert truth(p, expression) is False


def test_ambiguity_identity_is_stable_when_the_material_portfolio_is_rebuilt():
    p = candidate(curve([point()] * 5), curve([point()] * 5))
    diagnostics = []
    condition = predicate(f'count({LC}.points) >= 5')
    assert not evaluate_portfolio_predicate(p, condition, diagnostics=diagnostics)
    rebuilt = replace(p, internal_portfolio_id=InternalPortfolioId('rebuilt'))
    assert not evaluate_portfolio_predicate(rebuilt, condition, diagnostics=diagnostics)
    assert len(diagnostics) == 1
    assert 'candidate=ztf/object-1' in diagnostics[0]


def test_mixed_band_conditions_treat_absent_branches_as_false_not_unknown():
    p = candidate(curve([point('g', mag=20)]))
    for condition in ('photometry.g.psf.mag exists and photometry.r.psf.mag < 19',
                      'photometry.g.psf.mag < 19 or photometry.r.psf.mag < 19'):
        expression = f'count({LC}.points where {condition}) = 0'
        assert truth(p, expression, proof(p)) is True
