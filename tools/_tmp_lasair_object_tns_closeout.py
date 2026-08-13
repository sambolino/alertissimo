#!/usr/bin/env python3
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
mp = ROOT / 'alertissimo/data_layer/providers/lasair/ztf/mappings.yaml'
dp = ROOT / 'alertissimo/data_layer/providers/lasair/ztf/unmapped_fields.yaml'
tp = ROOT / 'tests/test_lasair_ztf_live_capture.py'

m = yaml.safe_load(mp.read_text())
m['payloads']['objects_candidates'] = {'endpoint': 'objects', 'path': '[].candidates[]'}

def add(path, *refs):
    out = m['mappings'].setdefault(path, [])
    for ref in refs:
        if ref not in out:
            out.append(ref)

add('summary@ztf:lasair.detection_count', 'object#count_all_candidates', 'objects#count_all_candidates')
add('summary@ztf:lasair.time.first_mjd', 'object#objectData.discMjd', 'objects#objectData.discMjd')
add('summary@ztf:lasair.time.last_mjd', 'object#objectData.latestMjd', 'objects#objectData.latestMjd')
add('summary@ztf:lasair.time.first_detection', 'object#objectData.discUtc', 'objects#objectData.discUtc')
add('summary@ztf:lasair.time.last_detection', 'object#objectData.latestUtc', 'objects#objectData.latestUtc')

candidate_fields = {
'identity.source_id':'candid','identity.night_id':'nid','position.ra':'ra','position.dec':'dec',
'photometry.{filter}':'fid','photometry.{filter}.limit.mag':'diffmaglim',
'photometry.{filter}.limit.upper_limit':'diffmaglim',
'reference_image.nearest_source.photometry.{filter}.mag':'magnr',
'reference_image.nearest_source.photometry.{filter}.mag.error':'sigmagnr',
'calibration.{filter}.zero_point':'magzpsci','quality.real_bogus':'drb',
'image_metrics.is_positive':'isdiffpos','solar_system.mpc_match.identity.object_id':'ssnamenr',
'solar_system.mpc_match.separation.total':'ssdistnr'}
for suffix, raw in candidate_fields.items():
    add('detection@ztf:lasair.' + suffix, 'objects_candidates#' + raw)
add('detection@ztf:lasair.time.mjd', 'candidates#mjd', 'objects_candidates#jd', 'objects_candidates#mjd')
add('detection@ztf:lasair.time.datetime', 'candidates#utc', 'objects_candidates#utc')

for path, refs in list(m['mappings'].items()):
    for ref in list(refs):
        if ref.startswith('object#sherlock.'):
            twin = 'objects#' + ref[len('object#'):]
            if twin not in refs:
                refs.append(twin)

add('classification@tns:lasair.best.class', 'objects#TNS.type')
add('crossmatch@tns:lasair.identity.object_id', 'object#TNS.tns_name', 'objects#TNS.name', 'objects#TNS.tns_name')
add('crossmatch@tns:lasair.position.ra', 'objects#TNS.ra')
add('crossmatch@tns:lasair.position.dec', 'objects#TNS.decl')
add('crossmatch@tns:lasair.separation.total', 'object#TNS.arcsec', 'objects#TNS.arcsec')
add('crossmatch@tns:lasair.photometry.{filter}', 'object#TNS.disc_mag_filter', 'objects#TNS.disc_mag_filter')
add('crossmatch@tns:lasair.photometry.{filter}.mag', 'object#TNS.disc_mag', 'objects#TNS.disc_mag')
add('crossmatch@tns:lasair.redshift.value', 'objects#TNS.z')
add('crossmatch@{producer}:lasair.photometry.{filter}', 'object#sherlock.MagFilter', 'objects#sherlock.MagFilter')
add('crossmatch@{producer}:lasair.photometry.{filter}.mag', 'object#sherlock.Mag', 'objects#sherlock.Mag')
add('crossmatch@{producer}:lasair.photometry.{filter}.mag.error', 'object#sherlock.MagErr', 'objects#sherlock.MagErr')

tr = m.setdefault('transforms', {})
tr.setdefault('detection@ztf:lasair.time.mjd', {})['objects_candidates#jd'] = {'type':'jd_to_mjd'}
tr.setdefault('detection@ztf:lasair.photometry.{filter}', {})['objects_candidates#fid'] = {'type':'value_map','map':{1:'g',2:'r',3:'i'}}
tr.setdefault('detection@ztf:lasair.photometry.{filter}.limit.upper_limit', {})['objects_candidates#diffmaglim'] = {'type':'value_map','map':{},'default':True,'skip_null':True}
tr.setdefault('detection@ztf:lasair.image_metrics.is_positive', {})['objects_candidates#isdiffpos'] = {'type':'value_map','map':{'t':True,'f':False}}
tr.setdefault('detection@ztf:lasair.solar_system.mpc_match.identity.object_id', {})['objects_candidates#ssnamenr'] = {'type':'value_map','map':{'':None,'null':None,'-999':None,'-999.0':None,'Unknown':None},'skip_null':True}
tr.setdefault('detection@ztf:lasair.solar_system.mpc_match.separation.total', {})['objects_candidates#ssdistnr'] = {'type':'value_map','map':{-999:None},'skip_null':True}
producer_tr = tr['crossmatch@{producer}:lasair.provenance.producer.id']
producer_tr['objects#sherlock.catalogue_table_name'] = {'type':'value_map','map':dict(producer_tr['object#sherlock.catalogue_table_name']['map'])}
mp.write_text(yaml.safe_dump(m, sort_keys=False, width=120))

d = yaml.safe_load(dp.read_text())
existing = {next(iter(x)) for x in d.get('unmapped', [])}
def debt(ref, reason='authoritative_field_deferred'):
    if ref not in existing:
        d['unmapped'].append({ref:{'reason':reason,'candidate_meaning':'Observed authoritative Lasair/ZTF field intentionally deferred; no ontology change in this close-out.'}})
        existing.add(ref)

for ref in ['objects_candidates#magpsf','objects_candidates#sigmapsf']:
    debt(ref,'conditional_detection_presence_required')
for prefix in ['candidates','objects_candidates']:
    for raw in ['image_urls.Science','image_urls.Template','image_urls.Difference','imjd','since_now','json']:
        debt(prefix+'#'+raw)

root = ['objectData.glonmean','objectData.glatmean','objectData.ec_lon','objectData.ec_lat','objectData.rasex','objectData.decsex',
'objectData.now_mjd','objectData.mjdmin_ago','objectData.mjdmax_ago','objectData.discMag','objectData.discFilter',
'objectData.latestMag','objectData.latestFilter','objectData.peakMjd','objectData.peakUtc','objectData.peakMag','objectData.peakFilter',
'count_isdiffpos','count_isdiffneg','count_noncandidate','message','sherlock.objectId','sherlock.distance','sherlock.photoZ',
'sherlock.photoZErr','sherlock.major_axis_arcsec','sherlock.annotator','sherlock.additional_output','sherlock.summary',
'TNS.tns_prefix','TNS.disc_int_name','TNS.disc_date','TNS.disc_date_mjd','TNS.lastmodified_date','TNS.lastmodified_date_mjd',
'TNS.lasairmodified_date','TNS.lasairmodified_date_mjd','TNS.sender','TNS.reporters','TNS.source_group','TNS.htm16','TNS.id',
'TNS.objectId','TNS.wl_id','TNS.cone_id']
for raw in root:
    debt('object#'+raw)
    debt('objects#'+raw)
dp.write_text(yaml.safe_dump(d, sort_keys=False, width=120))

t = tp.read_text()
if 'test_live_object_and_plural_object_are_fully_accounted' not in t:
    marker='\ndef test_live_lightcurve_is_fully_accounted_with_detections_and_limits() -> None:\n'
    test='''\n\ndef test_live_object_and_plural_object_are_fully_accounted() -> None:\n    obj = _fixture("object_default")\n    objs = _fixture("objects_plural")\n    _assert_zero_unaccounted("object", "object_default")\n    _assert_zero_unaccounted("objects", "objects_plural")\n    assert len(obj["candidates"]) == 92\n    portfolio = _build("object", obj)\n    summary = next(r for r in portfolio.records if r.semantic_type == "summary@ztf:lasair")\n    assert summary.fields["detection_count"] == 35\n    assert summary.fields["time.first_detection"] == "2020-11-12 10:27:04"\n    tns = next(r for r in portfolio.records if r.semantic_type == "crossmatch@tns:lasair")\n    assert tns.fields["separation.total"] == pytest.approx(0.12)\n    assert tns.fields["photometry.r.mag"] == pytest.approx(19.7399)\n    plural = _build("objects", objs)\n    assert len([r for r in plural.records if r.semantic_type == "detection@ztf:lasair"]) == 92\n'''
    if marker not in t: raise RuntimeError('test insertion marker missing')
    t=t.replace(marker,test+marker,1)
    tp.write_text(t)
