"""Regression tests against the frozen authenticated Lasair/LSST capture."""
from __future__ import annotations
from itertools import count
import json
from pathlib import Path
import pytest
import yaml
from alertissimo.data_layer.execution import ExecutionResult
from alertissimo.data_layer.representations import InternalExecutionId, InternalExecutionProvenance, InternalPortfolioId, InternalRecordId
from alertissimo.data_layer.runtime.record_builder import build_portfolio_from_execution
from tools.audit_payload_mapping_coverage import audit_payload
CAPTURE=Path(__file__).parent/'fixtures/lasair/lsst/capture_20260813T140948Z'
MAPPINGS=Path(__file__).parents[1]/'alertissimo/data_layer/providers/lasair/lsst/mappings.yaml'
ENDPOINTS=Path(__file__).parents[1]/'alertissimo/data_layer/providers/lasair/lsst/endpoints.yaml'
def _fixture(name):return json.loads((CAPTURE/f'{name}.json').read_text())
def _build(endpoint,payload):
 eid=InternalExecutionId(f'execution:fixture:{endpoint}');ids=count()
 return build_portfolio_from_execution(ExecutionResult(payload=payload,execution_provenance=InternalExecutionProvenance(internal_execution_id=eid,broker='lasair',origin='lsst',endpoint=endpoint)),mappings_path=MAPPINGS,internal_portfolio_id=InternalPortfolioId('portfolio:fixture'),record_id_factory=lambda:InternalRecordId(f'record:{next(ids)}'),validate_semantic_model=True)
def _zero(endpoint,name):
 report=audit_payload(_fixture(name),broker='lasair',origin='lsst',endpoint=endpoint,payload_file=str(CAPTURE/f'{name}.json'));assert 'Unaccounted leaves: 0' in report

def test_live_lsst_surface_shapes_are_frozen():
 c=_fixture('object_with_context');r=_fixture('object_raw')
 assert c['diaObjectId']=='313761042336317573';assert 'lasairData' in c;assert 'lasairData' not in r
 assert len(c['diaSourcesList'])==245;assert len(c['diaForcedSourcesList'])==345
 assert c['lasairData']['nDiaSources']==259;assert r['diaObject']['nDiaSources']==259
 assert _fixture('cone_all')=={'objects':[{'object':313761042336317573,'separation':0.0}],'count':1,'nearest':{'object':313761042336317573,'separation':0.0}}
 assert _fixture('cone_nearest')=={'nearest':{'object':313761042336317573,'separation':0.0}};assert _fixture('cone_count')=={'count':1}
 assert _fixture('query_object')==[{'diaObjectId':313761042336317573}];assert _fixture('query_object_qualified')==[{'diaObjectId':313761042336317573}]
 assert yaml.safe_load(ENDPOINTS.read_text())['endpoints']['cone']['output']['type']=='object'

def test_live_object_variants_are_fully_accounted_and_build_records():
 for name in ('object_default','object_with_context','object_raw'):_zero('object',name)
 p=_fixture('object_with_context');portfolio=_build('object',p)
 summary=next(r for r in portfolio.records if r.semantic_type=='summary@lsst:lasair');f=dict(summary.fields)
 assert f['identity.object_id']=='313761042336317573';assert f['detection_count']==259
 assert f['time.first_mjd']==pytest.approx(61003.324393250674);assert f['time.last_mjd']==pytest.approx(61235.41918367943)
 types={r.semantic_type for r in portfolio.records};assert 'detection@lsst:lasair' in types;assert 'classification@sherlock:lasair' in types;assert 'crossmatch@desi_legacy_survey:lasair' in types
 det=[r for r in portfolio.records if r.semantic_type=='detection@lsst:lasair'];assert len(det)>=len(p['diaSourcesList'])
 assert any(any(k.startswith('photometry.') and k.endswith('.psf.flux') for k in r.fields) for r in det)
 assert any(any(k.startswith('forced_photometry.') and k.endswith('.psf.flux') for k in r.fields) for r in det)

def test_live_query_and_cone_all_are_fully_accounted():
 _zero('query','query_object');_zero('query','query_object_qualified');_zero('cone','cone_all')
 q=next(r for r in _build('query',_fixture('query_object')).records if r.semantic_type=='summary@lsst:lasair');assert q.fields['identity.object_id']==313761042336317573
 c=next(r for r in _build('cone',_fixture('cone_all')).records if r.semantic_type=='summary@lsst:lasair');assert c.fields['identity.object_id']==313761042336317573

def test_live_sherlock_lite_and_full_are_fully_accounted():
 for endpoint,names in (('sherlock_object',('sherlock_object_lite','sherlock_object_full')),('sherlock_position',('sherlock_position_lite','sherlock_position_full'))):
  for name in names:_zero(endpoint,name)
 full=_fixture('sherlock_object_full');assert len(full['crossmatches'])==2;portfolio=_build('sherlock_object',full)
 types={r.semantic_type for r in portfolio.records};assert 'classification@sherlock:lasair' in types;assert 'crossmatch@desi_legacy_survey:lasair' in types
 matches=[r for r in portfolio.records if r.semantic_type=='crossmatch@desi_legacy_survey:lasair'];assert sorted(r.fields['rank'] for r in matches)==[1,2]
 first=next(r for r in matches if r.fields['rank']==1);assert first.fields['photometry.W1.mag']==pytest.approx(18.4319);assert first.fields['photometry.r.mag']==pytest.approx(20.4716)

def test_lsst_sherlock_does_not_restore_known_bad_shortcuts():
 d=yaml.safe_load(MAPPINGS.read_text());m=d['mappings'];t=d['transforms'];p=d['payloads']
 assert p['diaForcedSourcesList']=={'endpoint':'object','path':'diaForcedSourcesList[]'};assert p['cone_objects']=={'endpoint':'cone','path':'objects[]'}
 assert all('photoZ' not in r for r in m.get('crossmatch@{producer}:lasair.redshift.value',[]));assert 'crossmatch@{producer}:lasair.redshift.error' not in m
 assert all('merged_rank' not in r for r in m['crossmatch@{producer}:lasair.rank'])
 for spec in t['crossmatch@{producer}:lasair.provenance.producer.id'].values():assert spec.get('default')!='unknown';assert spec['map']['DESI']=='desi_legacy_survey'
