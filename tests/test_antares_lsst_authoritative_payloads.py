"""Authoritative audit of frozen antares-client 1.14.0 LSST evidence."""
from __future__ import annotations
import copy,json
from itertools import count
from pathlib import Path
import pytest,yaml
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId,InternalExecutionProvenance,InternalPortfolioId,InternalRecordId
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload
FIXTURES=Path(__file__).parent/'fixtures/antares/lsst'
MAPPINGS=Path(__file__).parents[1]/'alertissimo/data_layer/providers/antares/lsst/mappings.yaml'
def fixture(n):return json.loads((FIXTURES/n).read_text())
def rich_locus(catalogs=False):
 x=copy.deepcopy(fixture('get_by_lsst_dia_object_id.json'));x['alerts']=fixture('alerts.json');x['catalog_objects']={}
 if catalogs:
  for match in fixture('catalog_crossmatch_probe.json')['matches']:
   for family,rows in match['catalog_objects'].items():x['catalog_objects'].setdefault(family,[]).extend(rows)
 return x
class LazyLocus(dict):
 @property
 def lightcurve(self):raise AssertionError('production normalization accessed lazy Locus.lightcurve')
def build(endpoint,payload):
 ids=count();return build_portfolio_from_execution(ExecutionResult(payload=payload,execution_provenance=InternalExecutionProvenance(internal_execution_id=InternalExecutionId('execution:fixture'),broker='antares',origin='lsst',endpoint=endpoint)),mappings_path=MAPPINGS,internal_portfolio_id=InternalPortfolioId('portfolio:fixture'),record_id_factory=lambda:InternalRecordId(f'record:{next(ids)}'),validate_semantic_model=True)
def records(p,k):return [r for r in p.records if r.semantic_type==k]
@pytest.mark.parametrize(('name','endpoint'),[('get_by_lsst_dia_object_id.json','get_by_lsst_dia_object_id'),('get_by_id.json','get_by_id'),('search.json','search'),('cone_search.json','cone_search')])
def test_locus_surfaces_zero_unaccounted(name,endpoint):assert 'Unaccounted leaves: 0' in audit_payload(fixture(name),broker='antares',origin='lsst',endpoint=endpoint)
def test_authoritative_alert_semantics_and_aliases():
 alerts=fixture('alerts.json');assert len(alerts)==16 and all(a['alert_id'].startswith('lsst:') for a in alerts)
 assert all(a['mjd']==a['properties']['ant_mjd']==a['properties']['lsst_diaSource_midpointMjdTai'] for a in alerts)
 assert all(a['properties']['ant_ra']==a['properties']['lsst_diaSource_ra'] and a['properties']['ant_dec']==a['properties']['lsst_diaSource_dec'] for a in alerts)
 assert all(a['properties']['ant_maglim']==a['properties']['ant_mag'] for a in alerts)
 p=build('get_by_lsst_dia_object_id',rich_locus());ds=records(p,'detection@lsst:antares');assert len(ds)==16
 sf=dict(records(p,'summary@lsst:antares')[0].fields);assert sf['identity.object_id']==170587117485817955 and isinstance(sf['identity.object_id'],int) and sf['identity.antares_locus_id']=='ANT2026rq61krn5dipt';assert 'detection_count' not in sf and not any(k.startswith('time.') for k in sf)
 assert all(dict(d.fields)['identity.object_id']==170587117485817955 and isinstance(dict(d.fields)['identity.object_id'],int) for d in ds)
 f=dict(ds[0].fields);assert {'identity.alert_id','identity.source_id','identity.object_id','identity.visit_id','identity.detector_id'}<=f.keys();assert f['quality.signal_to_noise']==alerts[0]['properties']['lsst_diaSource_snr'];assert isinstance(f['image_metrics.is_positive'],bool);assert p.edges==()
def test_strict_unknown_band_is_omitted():
 x=rich_locus();x['alerts']=[copy.deepcopy(x['alerts'][0])];x['alerts'][0]['properties']['lsst_diaSource_band']='X';f=dict(records(build('get_by_lsst_dia_object_id',x),'detection@lsst:antares')[0].fields);assert not any(k.startswith(('photometry.','calibration.')) or '{filter}' in k or 'photometry.X' in k for k in f)
def test_lightcurve_is_fixture_only_and_lazy_untouched():
 light=fixture('lightcurve.json');cols={k for r in light for k in r};debt=yaml.safe_load((FIXTURES/'lightcurve_secondary_debt.yaml').read_text())['lightcurve_secondary'];assert len(light)==16 and len(cols)==14 and cols==set(debt);assert all(v['reason']=='secondary_duplicate_representation' for v in debt.values())
 registry=yaml.safe_load(MAPPINGS.read_text());assert all('lightcurve' not in d['path'] for d in registry['payloads'].values());assert len(records(build('get_by_lsst_dia_object_id',LazyLocus(rich_locus())),'detection@lsst:antares'))==16
def test_catalog_probe_direct_rows_zero_unaccounted_and_no_edges():
 x=rich_locus(True);report=audit_payload(x,broker='antares',origin='lsst',endpoint='get_by_lsst_dia_object_id');assert 'Unaccounted leaves: 0' in report
 p=build('get_by_lsst_dia_object_id',x);assert {r.semantic_type for r in p.records if r.semantic_type.startswith('crossmatch@')}=={'crossmatch@allwise:antares','crossmatch@gsc:antares','crossmatch@gaia:antares','crossmatch@gaia_variability:antares','crossmatch@milliquas:antares','crossmatch@ned:antares'};assert len(records(p,'detection@lsst:antares'))==16 and p.edges==()
 gaia=[dict(r.fields) for r in records(p,'crossmatch@gaia:antares')]
 expected={'color.BP-RP.diff':0.6110668,'color.BP-G.diff':0.053186417,'color.G-RP.diff':0.5578804,'classification.assessment.gaia_dsc_galaxy.probability':1.3322759e-08,'classification.assessment.gaia_dsc_quasar.probability':0.97776324,'classification.assessment.gaia_dsc_star.probability':0.022236746}
 assert any(all(row.get(key)==value for key,value in expected.items()) for row in gaia)
def test_search_cone_and_by_id_summaries():
 for name,endpoint in [('get_by_id.json','get_by_id'),('search.json','search'),('cone_search.json','cone_search')]:assert len(records(build(endpoint,fixture(name)), 'summary@lsst:antares'))==1

def test_promoted_antares_features_have_locus_surface_parity():
 expected=None
 paths={'photometry.i.mag.mean','photometry.i.mag.half_amplitude','photometry.i.flux.chi2'}
 debt=(MAPPINGS.parent/'unmapped_fields.yaml').read_text()
 for name,endpoint in [('get_by_lsst_dia_object_id.json','get_by_lsst_dia_object_id'),('get_by_id.json','get_by_id'),('search.json','search'),('cone_search.json','cone_search')]:
  values=dict(records(build(endpoint,fixture(name)),'summary@antares')[0].fields)
  current={path:values[path] for path in paths}
  expected=current if expected is None else expected
  assert current==expected
  prefix={'get_by_lsst_dia_object_id':'locus','get_by_id':'locus_by_id','search':'search_loci','cone_search':'cone_loci'}[endpoint]
  assert all(f'{prefix}#properties.feature_{raw}:' not in debt for raw in ('mean_magn_i','amplitude_magn_i','chi2_flux_i'))

def test_historical_diaobject_snapshots_and_antares_feature_producer():
 alerts=fixture('alerts.json');p=build('get_by_lsst_dia_object_id',rich_locus())
 snapshots=[dict(r.fields) for r in records(p,'summary@lsst:antares') if 'time.snapshot_mjd' in dict(r.fields)]
 assert len(records(p,'detection@lsst:antares'))==len(snapshots)==16
 expected=['identity.object_id','time.snapshot_mjd','position.ra','position.dec','position.ra_error','position.dec_error','position.ra_dec_covariance','detection_count']
 for raw,snapshot in zip(alerts,snapshots,strict=True):
  props=raw['properties'];assert all(k in snapshot for k in expected)
  assert snapshot['identity.object_id']==int(props['lsst_diaObject_diaObjectId'])
  assert snapshot['time.snapshot_mjd']==props['lsst_diaObject_validityStartMjdTai']
  assert snapshot['detection_count']==props['lsst_diaObject_nDiaSources']
  for semantic,raw_name in [('position.ra','ra'),('position.dec','dec'),('position.ra_error','raErr'),('position.dec_error','decErr'),('position.ra_dec_covariance','ra_dec_Cov')]:assert snapshot[semantic]==props['lsst_diaObject_'+raw_name]
 assert [s['detection_count'] for s in snapshots]==[a['properties']['lsst_diaObject_nDiaSources'] for a in alerts]
 assert all(isinstance(s['identity.object_id'],int) for s in snapshots) and p.edges==()
 antares=dict(records(p,'summary@antares')[0].fields)
 assert {'photometry.i.mag.mean','photometry.i.mag.half_amplitude','photometry.r.mag.excess_kurtosis','photometry.i.flux.chi2'}<=antares.keys()
 assert not any('magnitude.' in k or '.flux.chi2' in k for s in snapshots for k in s)

def test_diaobject_psf_aggregates_follow_frozen_alert_values():
 alerts=fixture('alerts.json');snapshots=[dict(r.fields) for r in records(build('get_by_lsst_dia_object_id',rich_locus()),'summary@lsst:antares') if 'time.snapshot_mjd' in dict(r.fields)]
 suffix={'psfFluxMean':'flux.mean','psfFluxMeanErr':'flux.mean_error','psfFluxErrMean':'flux.error_mean','psfFluxMax':'flux.maximum','psfFluxMin':'flux.minimum','psfFluxSigma':'flux.sigma','psfFluxNdata':'flux.measurement_count','psfFluxMaxSlope':'flux.maximum_slope'}
 for raw,snapshot in zip(alerts,snapshots,strict=True):
  for key,value in raw['properties'].items():
   for band in 'ugrizy':
    prefix=f'lsst_diaObject_{band}_'
    if key.startswith(prefix) and key[len(prefix):] in suffix:assert snapshot[f'photometry.{band}.psf.{suffix[key[len(prefix):]]}']==value
