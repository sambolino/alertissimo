"""Authoritative semantic audit of frozen antares-client 1.14.0 ZTF evidence."""
from __future__ import annotations
import copy, hashlib, json
from itertools import count
from pathlib import Path
import pytest
import yaml
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId, InternalRecordId
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload

FIXTURES=Path(__file__).parent/'fixtures/antares/ztf'
MAPPINGS=Path(__file__).parents[1]/'alertissimo/data_layer/providers/antares/ztf/mappings.yaml'
def fixture(name): return json.loads((FIXTURES/name).read_text())
def rich_locus():
    # Independently frozen client-visible core and lazy relationships are composed
    # only in memory; this is not represented as one raw HTTP response.
    value=copy.deepcopy(fixture('get_by_ztf_object_id.json'))
    value['alerts']=fixture('alerts.json'); value['catalog_objects']=fixture('catalog_objects.json')
    return value
class LazyLightcurveLocus(dict):
    @property
    def lightcurve(self):
        raise AssertionError('production normalization accessed lazy Locus.lightcurve')
def build(endpoint,payload):
    ids=count()
    return build_portfolio_from_execution(ExecutionResult(payload=payload,execution_provenance=InternalExecutionProvenance(internal_execution_id=InternalExecutionId('execution:fixture'),broker='antares',origin='ztf',endpoint=endpoint)),mappings_path=MAPPINGS,internal_portfolio_id=InternalPortfolioId('portfolio:fixture'),record_id_factory=lambda:InternalRecordId(f'record:{next(ids)}'),validate_semantic_model=True)
def records(portfolio,kind): return [r for r in portfolio.records if r.semantic_type==kind]

@pytest.mark.parametrize(('name','endpoint'),[('get_by_id.json','get_by_id'),('search.json','search'),('cone_search.json','cone_search')])
def test_core_fixtures_have_zero_unaccounted(name,endpoint):
    report=audit_payload(fixture(name),broker='antares',origin='ztf',endpoint=endpoint)
    assert 'Unaccounted leaves: 0' in report

def test_rich_composite_has_zero_unaccounted():
    report=audit_payload(rich_locus(),broker='antares',origin='ztf',endpoint='get_by_ztf_object_id')
    assert 'Mapped leaves: 85' in report
    assert 'Intentionally unmapped leaves: 817' in report
    assert 'Delegated / structural leaves: 712' in report
    assert 'Unaccounted leaves: 0' in report

def test_locus_and_complete_alert_semantics():
    portfolio=build('get_by_ztf_object_id',rich_locus())
    summary=records(portfolio,'summary@ztf:antares')[0]; sf=dict(summary.fields)
    assert sf['identity.object_id']=='ZTF20aafqubg'; assert sf['identity.antares_locus_id']=='ANT2020nb5h6'
    assert sf['position.ra']==50.84810593071894; assert sf['position.dec']==37.46783501531417
    assert 'detection_count' not in sf and not any(r.semantic_type.startswith('classification@') for r in portfolio.records)
    detections=records(portfolio,'detection@ztf:antares'); assert len(detections)==316
    fields=[dict(r.fields) for r in detections]; assert all('identity.alert_id' in f for f in fields)
    assert sum(f.get('photometry.g.limit.upper_limit') is False or f.get('photometry.r.limit.upper_limit') is False for f in fields)==70
    assert sum(f.get('photometry.g.limit.upper_limit') is True or f.get('photometry.r.limit.upper_limit') is True for f in fields)==246
    assert sum(any(k.startswith('photometry.r.') for k in f) for f in fields)==216
    assert sum(any(k.startswith('photometry.g.') for k in f) for f in fields)==100
    assert not any(any(k.startswith('photometry.R') for k in f) for f in fields)
    assert sum(any(k.endswith('.limit.mag') for k in f) for f in fields)==316
    assert sum(any(k.endswith('.psf.mag') for k in f) for f in fields)==70
    assert all(f['image_metrics.is_positive'] is False for f in fields if 'image_metrics.is_positive' in f)
    assert not any(r.semantic_type.startswith(('non_detection','forced_photometry')) for r in portfolio.records)
    assert portfolio.edges==()

def test_strict_unknown_encodings_are_omitted():
    alert=copy.deepcopy(next(x for x in fixture('alerts.json') if 'ztf_isdiffpos' in x['properties']))
    alert['properties']['ztf_isdiffpos']='unknown'; alert['properties']['ant_survey']=99; alert['properties']['ant_passband']='X'
    payload=copy.deepcopy(fixture('get_by_ztf_object_id.json')); payload['alerts']=[alert]
    fields=dict(records(build('get_by_ztf_object_id',payload),'detection@ztf:antares')[0].fields)
    assert 'image_metrics.is_positive' not in fields
    assert not any(k.endswith('upper_limit') for k in fields)
    assert not any('photometry.X' in k or '{filter}' in k for k in fields)
    assert not any(k.startswith(('photometry.', 'calibration.')) for k in fields)

def test_alert_aliases_and_lightcurve_secondary_evidence():
    alerts=fixture('alerts.json'); candidates=[a for a in alerts if a['alert_id'].startswith('ztf_candidate:')]
    for row in candidates:
        p=row['properties']; assert p['ant_mag']==p['ztf_magpsf']; assert p['ant_magerr']==p['ztf_sigmapsf']; assert p['ant_ra']==p['ztf_ra']; assert p['ant_dec']==p['ztf_dec']; assert p['ant_maglim']==p['ztf_diffmaglim']
    light=fixture('lightcurve.json'); assert len(light)==len({r['alert_id'] for r in light})==280
    observed_columns={key for row in light for key in row}
    expected_columns={'time','alert_id','ant_mjd','ant_survey','ant_ra','ant_dec','ant_passband','ant_mag','ant_magerr','ant_maglim','ant_mag_corrected','ant_magerr_corrected','ant_magulim_corrected','ant_magllim_corrected'}
    assert observed_columns==expected_columns and len(observed_columns)==14
    debt=yaml.safe_load((FIXTURES/'lightcurve_secondary_debt.yaml').read_text())['lightcurve_secondary']
    secondary=set(debt)
    registry=yaml.safe_load(MAPPINGS.read_text())
    raw_references={raw for references in registry['mappings'].values() for raw in references}
    mapped={raw.split('#',1)[1] for raw in raw_references if raw.startswith('lightcurve_secondary#')}
    assert all(details['reason']=='secondary_duplicate_representation' for details in debt.values())
    assert secondary==observed_columns
    assert {'observed':len(observed_columns),'mapped':len(mapped),'intentionally_secondary':len(secondary),'unaccounted':len(observed_columns-mapped-secondary)}=={'observed':14,'mapped':0,'intentionally_secondary':14,'unaccounted':0}
    alert_ids={r['alert_id'] for r in alerts}; assert {r['alert_id'] for r in light}<=alert_ids
    assert len(alert_ids-{r['alert_id'] for r in light})==36
    assert sum(r['alert_id'].startswith('ztf_candidate:') for r in light)==56
    portfolio=build('get_by_ztf_object_id',rich_locus())
    assert len(records(portfolio,'detection@ztf:antares'))==316
    assert not any(r.semantic_type=='lightcurve' for r in portfolio.records)

def test_lightcurve_is_not_registered_as_a_runtime_payload():
    registry=yaml.safe_load(MAPPINGS.read_text())
    assert all('lightcurve' not in payload['path'] for payload in registry['payloads'].values())
    raw_references={raw for references in registry['mappings'].values() for raw in references}
    assert not any(raw.startswith('lightcurve_secondary#') for raw in raw_references)
    portfolio=build('get_by_ztf_object_id',LazyLightcurveLocus(rich_locus()))
    assert len(records(portfolio,'detection@ztf:antares'))==316

def test_direct_catalog_rows_build_six_crossmatches():
    portfolio=build('get_by_ztf_object_id',rich_locus())
    expected={'crossmatch@twomass:antares','crossmatch@allwise:antares','crossmatch@gsc:antares','crossmatch@gaia:antares','crossmatch@gaia_variability:antares','crossmatch@bailer_jones:antares'}
    found={r.semantic_type for r in portfolio.records if r.semantic_type.startswith('crossmatch@')}; assert found==expected
    gaia=dict(records(portfolio,'crossmatch@gaia:antares')[0].fields); assert gaia['identity.object_id']==234619155551528704; assert gaia['astrometric_solution.parallax']==0.4750640015400165
    wise=dict(records(portfolio,'crossmatch@allwise:antares')[0].fields); assert wise['photometry.W1.mag']==11.433
    assert portfolio.edges==()

def test_search_cone_and_one_shot_iterator():
    assert len(records(build('search',(x for x in fixture('search.json'))),'summary@ztf:antares'))==1
    cone=build('cone_search',(x for x in fixture('cone_search.json'))); assert len(records(cone,'summary@ztf:antares'))==4
    assert not any('separation' in key for r in cone.records for key in r.fields); assert cone.edges==()
